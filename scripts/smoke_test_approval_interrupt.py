#!/usr/bin/env python3
"""Prove durable manager approval/rejection interrupt and resume behavior."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import psycopg
from langchain_cockroachdb import CockroachDBEngine, CockroachDBSaver, CockroachDBVectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.types import RetryPolicy
from psycopg.rows import dict_row


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.approval_store import (  # noqa: E402
    commit_approval_resolution,
    load_manager_resume_value,
    record_manager_decision,
)
from product_returns.decision_store import commit_return_decision  # noqa: E402
from product_returns.evidence import (  # noqa: E402
    create_fraud_assessment_node,
    create_order_lookup_node,
    create_policy_retrieval_node,
    retryable_evidence_error,
)
from product_returns.graph import build_evidence_graph  # noqa: E402
from product_returns.refund import (  # noqa: E402
    create_issue_refund_node,
    retryable_refund_error,
)
from product_returns.refund_store import commit_refund_completion  # noqa: E402
from product_returns.reservation import (  # noqa: E402
    create_reserve_return_items_node,
    retryable_reservation_error,
)
from product_returns.state import ReturnWorkflowState  # noqa: E402
from product_returns.workflow_runs import (  # noqa: E402
    claim_workflow_run,
    create_workflow_run,
    get_workflow_run,
)
from product_returns.workflow_worker import execute_graph_turn  # noqa: E402


CUSTOMER_ID = UUID("10000000-0000-4000-8000-000000000002")
ORDER_ID = UUID("30000000-0000-4000-8000-000000000002")


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def validated_url() -> str:
    url = required("CRDB_APP_URL")
    parsed = urlparse(url)
    if parsed.username != "product_returns_app" or parsed.path != "/product_returns":
        raise RuntimeError("CRDB_APP_URL must use the product_returns application role")
    return url


def build_graph(connection_url: str):
    model_name = required("OPENAI_CLASSIFIER_MODEL")
    reasoning_effort = required("OPENAI_CLASSIFIER_REASONING_EFFORT")
    embedding_model = required("OPENAI_EMBEDDING_MODEL")
    dimensions = int(required("OPENAI_EMBEDDING_DIMENSIONS"))
    namespace = required("POLICY_VECTOR_NAMESPACE")
    engine = CockroachDBEngine.from_connection_string(connection_url)
    vector_store = CockroachDBVectorStore(
        engine=engine,
        embeddings=OpenAIEmbeddings(model=embedding_model, dimensions=dimensions),
        collection_name=required("POLICY_VECTOR_TABLE"),
        namespace=namespace,
    )
    return build_evidence_graph(
        ChatOpenAI(model=model_name, reasoning_effort=reasoning_effort),
        model_name,
        reasoning_effort,
        order_lookup_node=create_order_lookup_node(connection_url),
        policy_retrieval_node=create_policy_retrieval_node(
            connection_url,
            vector_store,
            namespace,
            embedding_model,
            dimensions,
        ),
        fraud_assessment_node=create_fraud_assessment_node(connection_url),
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


def run_case(connection_url: str, *, manager_action: str) -> None:
    return_request_id = uuid4()
    run_id = uuid4()
    thread_id = f"approval-{manager_action}-{uuid4()}"
    graph_builder = build_graph(connection_url)

    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO return_requests (
                return_request_id, customer_id, order_id, request_text
            ) VALUES (%s, %s, %s, %s)
            RETURNING NOTHING
            """,
            (
                return_request_id,
                CUSTOMER_ID,
                ORDER_ID,
                "I want to return the vacuum from order DEMO-1002.",
            ),
        )

    try:
        create_workflow_run(
            connection_url,
            return_request_id=return_request_id,
            thread_id=thread_id,
            run_id=run_id,
        )
        lease_a = claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=f"approval-start-{uuid4()}",
            lease_seconds=30,
        )
        if lease_a is None:
            raise RuntimeError("Initial worker could not claim approval test")

        # Phase 1 owns resources only while executing. Closing this context
        # simulates complete worker shutdown during human wait.
        with CockroachDBSaver.from_conn_string(connection_url) as saver:
            graph = graph_builder.compile(checkpointer=saver)
            paused = execute_graph_turn(
                connection_url,
                graph=graph,
                lease=lease_a,
                initial_state={
                    "run_id": str(run_id),
                    "thread_id": thread_id,
                    "customer_id": "CUST-SALLY",
                    "order_number": "DEMO-1002",
                    "customer_message": (
                        "I want to return the vacuum from order DEMO-1002."
                    ),
                },
                round_name="approval",
                heartbeat_interval_seconds=5,
                lease_seconds=30,
            )
        if paused.next_nodes != ("await_manager_approval",):
            raise RuntimeError(f"Graph did not pause for approval: {paused.next_nodes}")
        decision = paused.values.get("decision")
        if decision is None or decision["outcome"] != "requires_approval":
            raise RuntimeError("DEMO-1002 did not require manager approval")
        waiting = commit_return_decision(
            connection_url,
            lease=paused.run,
            decision=decision,
            checkpoint_id=paused.checkpoint_id,
        )
        if waiting.run_status != "waiting_for_approval":
            raise RuntimeError("Workflow did not enter durable approval wait")
        dormant = get_workflow_run(connection_url, run_id)
        if dormant is None or dormant.lease_owner is not None:
            raise RuntimeError("Approval wait retained a live worker lease")
        if claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id="must-not-claim-before-human",
            lease_seconds=30,
        ) is not None:
            raise RuntimeError("Waiting workflow was runnable before manager response")

        # Phase 2 is an external CLI/API-style transaction. No graph or worker
        # needs to be alive when the manager acts.
        recorded = record_manager_decision(
            connection_url,
            run_id=run_id,
            decision=manager_action,
            decided_by="manager.demo",
            decision_note=f"Smoke-test {manager_action} decision.",
        )

        # Phase 3 starts later, claims the now-ready run, loads the response
        # from CockroachDB, and resumes the exact interrupted checkpoint.
        lease_b = claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=f"approval-resume-{uuid4()}",
            lease_seconds=30,
        )
        if lease_b is None or lease_b.lease_generation != 2:
            raise RuntimeError("Resume worker did not claim generation 2")
        resume_value = load_manager_resume_value(connection_url, run_id=run_id)
        if resume_value != recorded.resume_value:
            raise RuntimeError("Loaded resume value differs from durable manager decision")

        with CockroachDBSaver.from_conn_string(connection_url) as saver:
            resumed_graph = graph_builder.compile(checkpointer=saver)
            resumed = execute_graph_turn(
                connection_url,
                graph=resumed_graph,
                lease=lease_b,
                initial_state=None,
                resume_value=resume_value,
                round_name="approval_resume",
                heartbeat_interval_seconds=5,
                lease_seconds=30,
            )
        if not resumed.is_terminal:
            raise RuntimeError("Approval resume did not reach the end of its graph turn")
        if resumed.values.get("manager_decision") != resume_value:
            raise RuntimeError("Manager response was not checkpointed into graph state")
        if manager_action == "approved":
            refund_result = resumed.values.get("refund_result")
            if refund_result is None:
                raise RuntimeError("Approved resume did not issue a refund")
            resolution = commit_refund_completion(
                connection_url,
                lease=resumed.run,
                refund_result=refund_result,
                decision=decision,
                checkpoint_id=resumed.checkpoint_id,
            )
            expected_run_status = "completed"
            expected_request_status = "refunded"
        else:
            resolution = commit_approval_resolution(
                connection_url,
                lease=resumed.run,
                manager_decision=resume_value,
                checkpoint_id=resumed.checkpoint_id,
            )
            expected_run_status = "rejected"
            expected_request_status = "rejected"
        expected_next: list[str] = []
        if resolution.run_status != expected_run_status:
            raise RuntimeError("Approval resolution produced the wrong workflow status")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            result = connection.execute(
                """
                SELECT wr.run_status, wr.next_nodes, rr.request_status,
                       ar.approval_status, ar.decided_by,
                       ria.allocation_status,
                       ric.reserved_quantity, ric.refunded_quantity,
                       count(ae.audit_event_id) AS audit_count
                FROM workflow_runs AS wr
                JOIN return_requests AS rr ON rr.return_request_id = wr.return_request_id
                JOIN approval_requests AS ar ON ar.run_id = wr.run_id
                JOIN return_item_allocations AS ria
                  ON ria.return_request_id = wr.return_request_id
                JOIN return_item_capacity AS ric
                  ON ric.order_item_id = ria.order_item_id
                JOIN audit_events AS ae ON ae.run_id = wr.run_id
                WHERE wr.run_id = %s
                GROUP BY wr.run_status, wr.next_nodes, rr.request_status,
                         ar.approval_status, ar.decided_by,
                         ria.allocation_status,
                         ric.reserved_quantity, ric.refunded_quantity
                """,
                (run_id,),
            ).fetchone()
        if result is None:
            raise RuntimeError("Approval result rows are missing")
        if result["run_status"] != expected_run_status or result["next_nodes"] != expected_next:
            raise RuntimeError("Persisted workflow routing is incorrect")
        if result["request_status"] != expected_request_status:
            raise RuntimeError("Persisted return-request status is incorrect")
        if result["approval_status"] != manager_action:
            raise RuntimeError("Persisted manager decision is incorrect")
        if result["decided_by"] != "manager.demo" or result["audit_count"] != 3:
            raise RuntimeError("Manager identity or three-event audit trail is missing")
        expected_allocation = "refunded" if manager_action == "approved" else "released"
        expected_refunded = 1 if manager_action == "approved" else 0
        if (
            result["allocation_status"] != expected_allocation
            or result["reserved_quantity"] != 0
            or result["refunded_quantity"] != expected_refunded
        ):
            raise RuntimeError("Manager outcome did not update return-item capacity")

        print(
            f"PASS manager {manager_action}: durable wait had no lease, generation 2 "
            f"resumed checkpoint {resumed.checkpoint_id}, final={expected_run_status}."
        )
    finally:
        with CockroachDBSaver.from_conn_string(connection_url) as saver:
            saver.delete_thread(thread_id)
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
                (UUID("40000000-0000-4000-8000-000000000002"),),
            )
            connection.execute("DELETE FROM approval_requests WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "DELETE FROM demo_payment_provider_refunds WHERE run_id = %s",
                (run_id,),
            )


def main() -> int:
    validated_url_value = validated_url()
    required("OPENAI_API_KEY")
    run_case(validated_url_value, manager_action="approved")
    run_case(validated_url_value, manager_action="rejected")
    print("Durable approval interrupt/resume smoke test passed 2/2 paths.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Approval interrupt smoke test failed: {error}", file=sys.stderr)
        raise
