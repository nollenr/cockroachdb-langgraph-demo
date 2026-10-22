#!/usr/bin/env python3
"""Exercise the three parallel evidence nodes and targeted retry behavior."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen
from uuid import uuid4

from langchain_cockroachdb import (
    CockroachDBEngine,
    CockroachDBSaver,
    CockroachDBVectorStore,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.types import RetryPolicy


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.evidence import (  # noqa: E402
    TransientEvidenceError,
    create_fraud_assessment_node,
    create_order_lookup_node,
    create_policy_retrieval_node,
    retryable_evidence_error,
)
from product_returns.graph import build_evidence_graph  # noqa: E402
from product_returns.observability import (  # noqa: E402
    configure_observability,
    shutdown_observability,
    start_prometheus_metrics_server,
)
from product_returns.state import ReturnWorkflowState  # noqa: E402


EXPECTED_DATABASE = "product_returns"
EXPECTED_RUNTIME_USER = "product_returns_app"


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def validated_app_url() -> str:
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


def wait_for_evidence_metrics(prometheus_url: str, timeout_seconds: float) -> None:
    """Wait until Prometheus has scraped successes plus the deliberate failure."""

    queries = (
        (
            'sum(product_returns_node_executions_total{status="succeeded",'
            'node=~"lookup_order|retrieve_policy|assess_fraud"})',
            3,
        ),
        (
            'sum(product_returns_node_executions_total{status="failed",'
            'node="assess_fraud"})',
            1,
        ),
    )
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        all_ready = True
        for expression, expected in queries:
            url = (
                f"{prometheus_url.rstrip('/')}/api/v1/query?"
                f"{urlencode({'query': expression})}"
            )
            try:
                with urlopen(url, timeout=3) as response:
                    document = json.load(response)
                results = document.get("data", {}).get("result", [])
                value = float(results[0]["value"][1]) if results else 0
                if value < expected:
                    all_ready = False
            except (OSError, URLError, ValueError, KeyError, json.JSONDecodeError):
                all_ready = False
        if all_ready:
            return
        sleep(1)
    raise RuntimeError("Prometheus did not capture evidence-node metrics in time")


def main() -> int:
    connection_url = validated_app_url()
    required_environment("OPENAI_API_KEY")
    model_name = required_environment("OPENAI_CLASSIFIER_MODEL")
    reasoning_effort = required_environment("OPENAI_CLASSIFIER_REASONING_EFFORT")
    embedding_model = required_environment("OPENAI_EMBEDDING_MODEL")
    embedding_dimensions = int(required_environment("OPENAI_EMBEDDING_DIMENSIONS"))
    namespace = required_environment("POLICY_VECTOR_NAMESPACE")
    table_name = required_environment("POLICY_VECTOR_TABLE")
    scrape_timeout = float(required_environment("PROMETHEUS_SCRAPE_TIMEOUT_SECONDS"))

    configure_observability(
        service_name=required_environment("OTEL_SERVICE_NAME"),
        otlp_enabled=(
            required_environment("PRODUCT_RETURNS_OTLP_ENABLED").lower() == "true"
        ),
        otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    )
    start_prometheus_metrics_server(
        int(required_environment("PROMETHEUS_METRICS_PORT"))
    )

    embeddings = OpenAIEmbeddings(
        model=embedding_model,
        dimensions=embedding_dimensions,
    )
    engine = CockroachDBEngine.from_connection_string(connection_url)
    vector_store = CockroachDBVectorStore(
        engine=engine,
        embeddings=embeddings,
        collection_name=table_name,
        namespace=namespace,
    )

    nodes: dict[str, Callable[[ReturnWorkflowState], dict[str, Any]]] = {
        "lookup_order": create_order_lookup_node(connection_url),
        "retrieve_policy": create_policy_retrieval_node(
            connection_url,
            vector_store,
            namespace,
            embedding_model,
            embedding_dimensions,
        ),
        "assess_fraud": create_fraud_assessment_node(connection_url),
    }
    calls = {name: 0 for name in nodes}
    calls_lock = Lock()

    def counted(
        name: str,
        node: Callable[[ReturnWorkflowState], dict[str, Any]],
    ) -> Callable[[ReturnWorkflowState], dict[str, Any]]:
        def invoke(state: ReturnWorkflowState) -> dict[str, Any]:
            with calls_lock:
                calls[name] += 1
                attempt = calls[name]
            if name == "assess_fraud" and attempt == 1:
                raise TransientEvidenceError(
                    "Deliberate first-attempt failure for targeted-retry proof"
                )
            return node(state)

        return invoke

    chat_model = ChatOpenAI(model=model_name, reasoning_effort=reasoning_effort)
    graph_builder = build_evidence_graph(
        chat_model,
        model_name,
        reasoning_effort,
        order_lookup_node=counted("lookup_order", nodes["lookup_order"]),
        policy_retrieval_node=counted("retrieve_policy", nodes["retrieve_policy"]),
        fraud_assessment_node=counted("assess_fraud", nodes["assess_fraud"]),
        evidence_retry_policy=RetryPolicy(
            initial_interval=0.1,
            backoff_factor=1.0,
            max_interval=0.1,
            max_attempts=2,
            jitter=False,
            retry_on=retryable_evidence_error,
        ),
    )

    thread_id = f"evidence-smoke-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}
    try:
        with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
            graph = graph_builder.compile(checkpointer=checkpointer)
            result = graph.invoke(
                {
                    "run_id": str(uuid4()),
                    "thread_id": thread_id,
                    "customer_id": "CUST-RON",
                    "order_number": "DEMO-1001",
                    "customer_message": (
                        "I want to return the toaster from order DEMO-1001. "
                        "It is unused and I have all the packaging."
                    ),
                },
                config,
            )
            snapshot = graph.get_state(config)

            if result["classification"]["intent"] != "refund":
                raise RuntimeError("Classifier did not route the request as a refund")
            if not result["order_lookup"]["found"]:
                raise RuntimeError("Order lookup did not find DEMO-1001 for CUST-RON")
            if result["order_lookup"]["refundable_item_total"] != "53.99":
                raise RuntimeError("Order lookup returned the wrong refundable total")
            if not result["policy_evidence"]["verified"]:
                raise RuntimeError("Policy evidence was not verified")
            clause_keys = {
                citation["clause_key"]
                for citation in result["policy_evidence"]["citations"]
            }
            if "RET-ELIGIBILITY-001" not in clause_keys:
                raise RuntimeError(
                    "Standard return-window clause was absent from policy evidence"
                )
            if result["fraud_assessment"]["risk_level"] != "low":
                raise RuntimeError("CUST-RON should have low demo fraud risk")
            if calls != {
                "lookup_order": 1,
                "retrieve_policy": 1,
                "assess_fraud": 2,
            }:
                raise RuntimeError(f"Unexpected branch call counts: {calls}")
            for field in ("order_lookup", "policy_evidence", "fraud_assessment"):
                if snapshot.values.get(field) != result[field]:
                    raise RuntimeError(
                        f"Checkpointed {field} differs from the completed result"
                    )
            if snapshot.next:
                raise RuntimeError(f"Completed evidence graph still has work: {snapshot.next}")

            checkpoint_count = sum(1 for _ in checkpointer.list(config, limit=20))
            if checkpoint_count < 3:
                raise RuntimeError("Evidence run did not create the expected checkpoints")

            print(
                "PASS parallel evidence: order=1 call, policy=1 call, "
                "fraud=2 calls (one targeted retry)."
            )
            print(
                "PASS checkpoint: all three verified evidence results persisted; "
                f"history contains {checkpoint_count} checkpoints."
            )

            checkpointer.delete_thread(thread_id)
            if checkpointer.get_tuple(config) is not None:
                raise RuntimeError("Temporary evidence checkpoint cleanup failed")

        wait_for_evidence_metrics(
            required_environment("PROMETHEUS_URL"),
            scrape_timeout,
        )
        print(
            "Evidence-round smoke test successful: independent parallel state, "
            "targeted retry, durable checkpoints, policy verification, and "
            "observability all passed."
        )
        return 0
    finally:
        shutdown_observability()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Evidence-round smoke test failed: {error}", file=sys.stderr)
        raise
