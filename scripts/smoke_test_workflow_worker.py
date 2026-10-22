#!/usr/bin/env python3
"""Run the real evidence graph through lease, checkpoint, and recovery logic."""

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

import psycopg
from psycopg.rows import dict_row
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
from product_returns.refund import (  # noqa: E402
    create_issue_refund_node,
    retryable_refund_error,
)
from product_returns.refund_store import commit_refund_completion  # noqa: E402
from product_returns.reservation import (  # noqa: E402
    create_reserve_return_items_node,
    retryable_reservation_error,
)
from product_returns.reservation_store import commit_reservation_conflict  # noqa: E402
from product_returns.state import ReturnWorkflowState  # noqa: E402
from product_returns.workflow_runs import (  # noqa: E402
    claim_workflow_run,
    create_workflow_run,
    get_workflow_run,
)
from product_returns.workflow_worker import execute_graph_turn  # noqa: E402


EXPECTED_DATABASE = "product_returns"
EXPECTED_RUNTIME_USER = "product_returns_app"
CUSTOMER_ID = "10000000-0000-4000-8000-000000000001"
ORDER_ID = "30000000-0000-4000-8000-000000000001"
ORDER_ITEM_ID = "40000000-0000-4000-8000-000000000001"
OBSERVED_NODES = (
    "classify_request",
    "lookup_order",
    "retrieve_policy",
    "assess_fraud",
    "decide_return",
    "reserve_return_items",
    "issue_refund",
)


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
    return connection_url


def wait_for_workflow_metrics(prometheus_url: str, timeout_seconds: float) -> None:
    """Keep the short-lived worker scrapeable until all graph nodes are stored."""

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        all_ready = True
        for node_name in OBSERVED_NODES:
            expression = (
                "product_returns_node_executions_total{"
                f'node="{node_name}",status="succeeded"'
                "}"
            )
            url = (
                f"{prometheus_url.rstrip('/')}/api/v1/query?"
                f"{urlencode({'query': expression})}"
            )
            try:
                with urlopen(url, timeout=3) as response:
                    document = json.load(response)
                results = document.get("data", {}).get("result", [])
                value = float(results[0]["value"][1]) if results else 0
                if value < 1:
                    all_ready = False
            except (OSError, URLError, ValueError, KeyError, json.JSONDecodeError):
                all_ready = False
        if all_ready:
            return
        sleep(1)
    raise RuntimeError("Prometheus did not capture all workflow-node metrics in time")


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
            return node(state)

        return invoke

    graph_builder = build_evidence_graph(
        ChatOpenAI(model=model_name, reasoning_effort=reasoning_effort),
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
        reservation_node=create_reserve_return_items_node(connection_url),
        reservation_retry_policy=RetryPolicy(
            initial_interval=0.1,
            backoff_factor=1.0,
            max_interval=0.1,
            max_attempts=3,
            jitter=False,
            retry_on=retryable_reservation_error,
        ),
        refund_node=create_issue_refund_node(connection_url),
        refund_retry_policy=RetryPolicy(
            initial_interval=0.1,
            backoff_factor=1.0,
            max_interval=0.1,
            max_attempts=3,
            jitter=False,
            retry_on=retryable_refund_error,
        ),
    )

    return_request_id = uuid4()
    run_id = uuid4()
    thread_id = f"worker-smoke-{uuid4()}"
    lease_seconds = 2
    heartbeat_interval = 0.4

    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO return_requests (
                return_request_id,
                customer_id,
                order_id,
                request_text
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                return_request_id,
                CUSTOMER_ID,
                ORDER_ID,
                "I want to return the toaster from order DEMO-1001.",
            ),
        )

    try:
        created = create_workflow_run(
            connection_url,
            return_request_id=return_request_id,
            thread_id=thread_id,
            run_id=run_id,
        )
        worker_a = f"worker-a-{uuid4()}"
        lease_a = claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=worker_a,
            lease_seconds=lease_seconds,
        )
        if lease_a is None:
            raise RuntimeError("Worker A could not claim the new workflow")

        with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
            graph = graph_builder.compile(checkpointer=checkpointer)
            first_turn = execute_graph_turn(
                connection_url,
                graph=graph,
                lease=lease_a,
                initial_state={
                    "run_id": str(run_id),
                    "thread_id": thread_id,
                    "customer_id": "CUST-RON",
                    "order_number": "DEMO-1001",
                    "customer_message": (
                        "I want to return the toaster from order DEMO-1001."
                    ),
                },
                round_name="evidence",
                heartbeat_interval_seconds=heartbeat_interval,
                lease_seconds=lease_seconds,
            )
            if not first_turn.graph_executed or not first_turn.is_terminal:
                raise RuntimeError("Worker A did not complete the evidence graph")
            if calls != {
                "lookup_order": 1,
                "retrieve_policy": 1,
                "assess_fraud": 1,
            }:
                raise RuntimeError(f"Unexpected evidence calls after worker A: {calls}")
            if first_turn.run.state_version != 1:
                raise RuntimeError("Worker A did not publish state version 1")
            if first_turn.run.latest_checkpoint_id != first_turn.checkpoint_id:
                raise RuntimeError("Published checkpoint ID differs from stream event")

            print(
                "PASS worker A: real graph executed under heartbeat and published "
                f"checkpoint {first_turn.checkpoint_id}."
            )

            # Simulate a process death after durable publication but before the
            # run is released. No Python object remains active during the wait.
            sleep(lease_seconds + 0.5)
            worker_b = f"worker-b-{uuid4()}"
            lease_b = claim_workflow_run(
                connection_url,
                run_id=run_id,
                worker_id=worker_b,
                lease_seconds=lease_seconds,
            )
            if lease_b is None or lease_b.lease_generation != 2:
                raise RuntimeError("Worker B did not reclaim generation 2")

            recovery_turn = execute_graph_turn(
                connection_url,
                graph=graph,
                lease=lease_b,
                initial_state=None,
                round_name="evidence",
                heartbeat_interval_seconds=heartbeat_interval,
                lease_seconds=lease_seconds,
            )
            if recovery_turn.graph_executed:
                raise RuntimeError("Terminal published checkpoint was executed again")
            if recovery_turn.checkpoint_id != first_turn.checkpoint_id:
                raise RuntimeError("Worker B did not load the published checkpoint")
            if calls != {
                "lookup_order": 1,
                "retrieve_policy": 1,
                "assess_fraud": 1,
            }:
                raise RuntimeError(f"Evidence nodes reran during recovery: {calls}")

            decision = recovery_turn.values.get("decision")
            refund_result = recovery_turn.values.get("refund_result")
            reservation = recovery_turn.values.get("return_reservation")
            if reservation is not None and reservation["status"] == "conflict":
                committed = commit_reservation_conflict(
                    connection_url,
                    lease=lease_b,
                    reservation=reservation,
                    checkpoint_id=recovery_turn.checkpoint_id,
                )
            else:
                if decision is None or refund_result is None:
                    raise RuntimeError("Recovered checkpoint has no decision/refund result")
                committed = commit_refund_completion(
                    connection_url,
                    lease=lease_b,
                    refund_result=refund_result,
                    decision=decision,
                    checkpoint_id=recovery_turn.checkpoint_id,
                )
            if committed.run_status != "completed":
                raise RuntimeError("Refund workflow was not completed")
            if committed.return_request_status != "refunded":
                raise RuntimeError("Return request was not marked refunded")
            if committed.state_version != 2:
                raise RuntimeError("Decision commit did not advance state version")

            print(
                "PASS worker B: reclaimed generation 2, loaded the exact published "
                "checkpoint, skipped completed nodes, and committed its refund."
            )

            checkpointer.delete_thread(thread_id)

        final_run = get_workflow_run(connection_url, run_id)
        if final_run is None or final_run.run_status != "completed":
            raise RuntimeError("Final workflow row is not completed")
        if final_run.current_round != "completed" or final_run.next_nodes:
            raise RuntimeError("Final workflow row has incorrect completed routing")
        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            audit = connection.execute(
                """
                SELECT event_type, checkpoint_id, event_data
                FROM audit_events
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if audit is None or audit["event_type"] != "refund_succeeded":
            raise RuntimeError("Successful refund audit event was not recorded")
        if audit["checkpoint_id"] != first_turn.checkpoint_id:
            raise RuntimeError("Audit event is not linked to the decision checkpoint")
        if audit["event_data"]["decision"]["reason_codes"] != [
            "ELIGIBLE_STANDARD_RETURN"
        ]:
            raise RuntimeError("Audit event did not preserve the decision reason")
        wait_for_workflow_metrics(
            required_environment("PROMETHEUS_URL"),
            scrape_timeout,
        )
        print(
            "PASS observability: Prometheus scraped classification, all three "
            "evidence nodes, decide_return, reserve_return_items, and issue_refund."
        )
        print("Checkpoint-backed workflow worker integration smoke test passed.")
        return 0
    finally:
        shutdown_observability()
        with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
            checkpointer.delete_thread(thread_id)
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute("DELETE FROM audit_events WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM refund_attempts WHERE refund_id IN (SELECT refund_id FROM refunds WHERE run_id = %s)",
                (run_id,),
            )
            connection.execute("DELETE FROM refunds WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_item_allocations WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "DELETE FROM return_items WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "UPDATE return_item_capacity SET reserved_quantity = 0, refunded_quantity = 0, updated_at = now() WHERE order_item_id = %s",
                (ORDER_ITEM_ID,),
            )
            connection.execute(
                "DELETE FROM approval_requests WHERE run_id = %s", (run_id,)
            )
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "DELETE FROM demo_payment_provider_refunds WHERE run_id = %s",
                (run_id,),
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Workflow worker smoke test failed: {error}", file=sys.stderr)
        raise

