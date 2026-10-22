#!/usr/bin/env python3
"""Exercise request classification and CockroachDB checkpoint persistence."""

from __future__ import annotations

import os
import sys
import json
from time import monotonic, sleep
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4

from langchain_cockroachdb import CockroachDBSaver
from langchain_openai import ChatOpenAI


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.graph import build_classification_graph  # noqa: E402
from product_returns.observability import (  # noqa: E402
    configure_observability,
    prometheus_snapshot,
    shutdown_observability,
    start_prometheus_metrics_server,
)


EXPECTED_DATABASE = "product_returns"
EXPECTED_RUNTIME_USER = "product_returns_app"
TEST_CASES = (
    (
        "refund",
        "unspecified",
        ("unspecified",),
        "I want to return the toaster from order DEMO-1001 and receive a refund.",
    ),
    (
        "complaint",
        "unspecified",
        ("unspecified",),
        "The coffee maker is noisy and I want to complain. I am not asking for a return or refund.",
    ),
    (
        "complaint",
        "unspecified",
        ("unspecified",),
        "Should the outside of the toaster get warm? Do I need to be concerned?",
    ),
    (
        "ambiguous",
        "unspecified",
        ("unspecified",),
        "I need help with the coffee maker from order DEMO-1005.",
    ),
    (
        "refund",
        "not_activated",
        ("unspecified",),
        "I want to return the iPhone from order DEMO-1004. The phone has not been activated.",
    ),
    (
        "refund",
        "unspecified",
        ("overheating", "property_damage"),
        "I want to return the toaster. It gets really hot and I am worried it will scorch my countertop.",
    ),
)


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def validated_app_url() -> str:
    """Return app credentials only after validating their non-secret fields."""

    connection_url = required_environment("CRDB_APP_URL")
    parsed = urlparse(connection_url)
    if parsed.username != EXPECTED_RUNTIME_USER:
        raise RuntimeError(
            f"CRDB_APP_URL must use {EXPECTED_RUNTIME_USER!r}, not an owner identity"
        )
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"CRDB_APP_URL must target {EXPECTED_DATABASE!r}")
    if not parsed.hostname:
        raise RuntimeError("CRDB_APP_URL does not contain a database hostname")
    return connection_url


def wait_for_prometheus_scrape(
    prometheus_url: str,
    timeout_seconds: float,
) -> float:
    """Keep this process scrapeable until Prometheus stores its success count."""

    query = urlencode(
        {
            "query": (
                'product_returns_node_executions_total{'
                'node="classify_request",status="succeeded"}'
            )
        }
    )
    url = f"{prometheus_url.rstrip('/')}/api/v1/query?{query}"
    deadline = monotonic() + timeout_seconds

    while monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                document = json.load(response)
            results = document.get("data", {}).get("result", [])
            if results:
                value = float(results[0]["value"][1])
                if value >= 6:
                    return value
        except (OSError, URLError, ValueError, KeyError, json.JSONDecodeError):
            pass
        sleep(1)

    raise RuntimeError(
        "Prometheus did not capture the classifier metrics before the timeout"
    )


def main() -> int:
    connection_url = validated_app_url()
    required_environment("OPENAI_API_KEY")
    model_name = required_environment("OPENAI_CLASSIFIER_MODEL")
    reasoning_effort = required_environment("OPENAI_CLASSIFIER_REASONING_EFFORT")
    otlp_enabled = required_environment("PRODUCT_RETURNS_OTLP_ENABLED").lower() == "true"
    metrics_port = int(required_environment("PROMETHEUS_METRICS_PORT"))
    scrape_timeout_seconds = float(
        required_environment("PROMETHEUS_SCRAPE_TIMEOUT_SECONDS")
    )
    if not 1 <= scrape_timeout_seconds <= 60:
        raise RuntimeError(
            "PROMETHEUS_SCRAPE_TIMEOUT_SECONDS must be between 1 and 60"
        )
    configure_observability(
        service_name=required_environment("OTEL_SERVICE_NAME"),
        otlp_enabled=otlp_enabled,
        otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
    start_prometheus_metrics_server(metrics_port)
    print(f"Prometheus metrics available on port {metrics_port} during this run.")

    chat_model = ChatOpenAI(
        model=model_name,
        reasoning_effort=reasoning_effort,
    )
    graph_builder = build_classification_graph(
        chat_model,
        model_name,
        reasoning_effort,
    )
    completed_threads: list[str] = []

    with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
        graph = graph_builder.compile(checkpointer=checkpointer)

        for (
            expected_intent,
            expected_activation,
            expected_safety_categories,
            customer_message,
        ) in TEST_CASES:
            thread_id = f"classification-smoke-{uuid4()}"
            config = {"configurable": {"thread_id": thread_id}}
            run_id = str(uuid4())

            result = graph.invoke(
                {
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "customer_id": "classification-smoke-customer",
                    "customer_message": customer_message,
                },
                config,
            )
            classification = result.get("classification")
            if not classification:
                raise RuntimeError("Graph result is missing classification")
            if classification["intent"] != expected_intent:
                raise RuntimeError(
                    f"Expected {expected_intent!r}, got "
                    f"{classification['intent']!r} for {customer_message!r}"
                )
            if classification["needs_clarification"] != (
                expected_intent == "ambiguous"
            ):
                raise RuntimeError("needs_clarification does not match intent")
            activation_claim = classification["device_activation_claim"]
            if activation_claim["status"] != expected_activation:
                raise RuntimeError(
                    f"Expected activation claim {expected_activation!r}, got "
                    f"{activation_claim['status']!r} for {customer_message!r}"
                )
            if expected_activation == "unspecified":
                if activation_claim["supporting_text"] or activation_claim["verified_in_message"]:
                    raise RuntimeError("Unspecified activation claim was not empty")
            elif (
                not activation_claim["verified_in_message"]
                or activation_claim["supporting_text"].casefold()
                not in customer_message.casefold()
            ):
                raise RuntimeError("Activation claim is not grounded in the message")

            safety_concern = classification["product_safety_concern"]
            if safety_concern["category"] not in expected_safety_categories:
                raise RuntimeError(
                    f"Expected safety category in {expected_safety_categories!r}, got "
                    f"{safety_concern['category']!r} for {customer_message!r}"
                )
            if expected_safety_categories == ("unspecified",):
                if (
                    safety_concern["status"] != "unspecified"
                    or safety_concern["supporting_text"]
                    or safety_concern["verified_in_message"]
                ):
                    raise RuntimeError("Unspecified safety concern was not empty")
            elif (
                safety_concern["status"] != "present"
                or not safety_concern["verified_in_message"]
                or safety_concern["supporting_text"].casefold()
                not in customer_message.casefold()
            ):
                raise RuntimeError("Safety concern is not grounded in the message")

            snapshot = graph.get_state(config)
            if snapshot.values.get("classification") != classification:
                raise RuntimeError("Persisted classification differs from graph result")

            print(
                f"PASS expected={expected_intent} "
                f"actual={classification['intent']} "
                f"activation={activation_claim['status']} "
                f"safety={safety_concern['category']} "
                f"confidence={classification['confidence']:.3f}"
            )
            completed_threads.append(thread_id)

        for thread_id in completed_threads:
            checkpointer.delete_thread(thread_id)
            deleted_config = {"configurable": {"thread_id": thread_id}}
            if checkpointer.get_tuple(deleted_config) is not None:
                raise RuntimeError(
                    f"Checkpoint cleanup failed for temporary thread {thread_id}"
                )

    metrics = prometheus_snapshot()
    expected_metric = (
        'product_returns_node_executions_total{node="classify_request",'
        'status="succeeded"} 6.0'
    )
    if expected_metric not in metrics:
        raise RuntimeError("Prometheus node-success counter did not reach 6")

    print(
        "Classification smoke test successful: 6/6 intents and grounded claims matched, "
        "CockroachDB checkpoints were verified and cleaned up, and node "
        "telemetry was recorded."
    )
    captured_count = wait_for_prometheus_scrape(
        required_environment("PROMETHEUS_URL"),
        scrape_timeout_seconds,
    )
    print(
        "Prometheus confirmed the captured classifier success counter at "
        f"{captured_count:g}."
    )
    shutdown_observability()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Classification smoke test failed: {error}", file=sys.stderr)
        raise

