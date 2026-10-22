#!/usr/bin/env python3
"""Prove that a post-provider failure cannot create a duplicate refund."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
from langchain_cockroachdb import CockroachDBSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from psycopg.rows import dict_row


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.refund import (  # noqa: E402
    TransientRefundError,
    create_issue_refund_node,
    refund_idempotency_key,
    retryable_refund_error,
)
from product_returns.refund_store import commit_refund_completion  # noqa: E402
from product_returns.reservation import reserve_return_quantities  # noqa: E402
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


def validated_app_url() -> str:
    connection_url = os.environ.get("CRDB_APP_URL")
    if not connection_url:
        raise RuntimeError("CRDB_APP_URL is not set")
    parsed = urlparse(connection_url)
    if parsed.username != EXPECTED_RUNTIME_USER:
        raise RuntimeError(f"CRDB_APP_URL must use {EXPECTED_RUNTIME_USER!r}")
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"CRDB_APP_URL must target {EXPECTED_DATABASE!r}")
    return connection_url


def main() -> int:
    connection_url = validated_app_url()
    return_request_id = uuid4()
    run_id = uuid4()
    thread_id = f"refund-smoke-{uuid4()}"
    crash_count = 0

    def fail_once_after_provider(*_args: object) -> None:
        nonlocal crash_count
        crash_count += 1
        if crash_count == 1:
            raise TransientRefundError(
                "Simulated worker failure after provider success"
            )

    refund_node = create_issue_refund_node(
        connection_url,
        after_provider_hook=fail_once_after_provider,
    )
    builder = StateGraph(ReturnWorkflowState)
    builder.add_node(
        "issue_refund",
        refund_node,
        retry_policy=RetryPolicy(
            initial_interval=0.1,
            backoff_factor=1.0,
            max_interval=0.1,
            max_attempts=2,
            jitter=False,
            retry_on=retryable_refund_error,
        ),
    )
    builder.add_edge(START, "issue_refund")
    builder.add_edge("issue_refund", END)

    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO return_requests (
                return_request_id, customer_id, order_id, request_text
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                return_request_id,
                CUSTOMER_ID,
                ORDER_ID,
                "Refund idempotency smoke test for order DEMO-1001.",
            ),
        )

    try:
        create_workflow_run(
            connection_url,
            return_request_id=return_request_id,
            thread_id=thread_id,
            run_id=run_id,
        )
        lease = claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=f"refund-worker-{uuid4()}",
            lease_seconds=30,
        )
        if lease is None:
            raise RuntimeError("Could not claim refund smoke-test run")

        initial_state: ReturnWorkflowState = {
            "run_id": str(run_id),
            "thread_id": thread_id,
            "customer_id": "CUST-RON",
            "order_number": "DEMO-1001",
            "customer_message": "Please refund the toaster.",
            "order_lookup": {
                "found": True,
                "customer_match": True,
                "order_number": "DEMO-1001",
                "order_id": ORDER_ID,
                "order_status": "delivered",
                "currency": "USD",
                "ordered_at": None,
                "days_since_order": 10,
                "refundable_item_total": "53.99",
                "shipping_amount": "0.00",
                "items": [
                    {
                        "order_item_id": "40000000-0000-4000-8000-000000000001",
                        "sku": "TOAST-2SL",
                        "product_name": "Two-Slice Toaster",
                        "product_category": "small_appliance",
                        "quantity": 1,
                        "unit_price": "49.99",
                        "tax_amount": "4.00",
                        "line_total": "53.99",
                        "activated_at": None,
                    }
                ],
            },
            "decision": {
                "outcome": "approved_for_refund",
                "next_action": "issue_refund",
                "eligible": True,
                "requires_manager_approval": False,
                "reason_codes": ["ELIGIBLE_STANDARD_RETURN"],
                "explanation": "Eligible standard return.",
                "calculated_refund_amount": "53.99",
                "approved_refund_amount": "53.99",
                "currency": "USD",
                "policy_citations": [],
                "facts": {},
            },
        }
        initial_state["return_reservation"] = reserve_return_quantities(
            connection_url,
            initial_state,
        )

        with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
            graph = builder.compile(checkpointer=checkpointer)
            turn = execute_graph_turn(
                connection_url,
                graph=graph,
                lease=lease,
                initial_state=initial_state,
                round_name="refund",
                heartbeat_interval_seconds=1.0,
                lease_seconds=30,
            )
            if not turn.is_terminal or not turn.graph_executed:
                raise RuntimeError("Refund graph did not reach its terminal checkpoint")
            refund_result = turn.values.get("refund_result")
            if refund_result is None:
                raise RuntimeError("Refund checkpoint contains no refund result")
            if crash_count != 2:
                raise RuntimeError(f"Refund node ran {crash_count} times, expected 2")
            if refund_result["provider_request_count"] != 2:
                raise RuntimeError("Provider did not observe the idempotent retry")

            committed = commit_refund_completion(
                connection_url,
                lease=turn.run,
                refund_result=refund_result,
                decision=turn.values["decision"],
                checkpoint_id=turn.checkpoint_id,
            )
            if committed.run_status != "completed":
                raise RuntimeError("Refund workflow was not completed")
            checkpointer.delete_thread(thread_id)

        final_run = get_workflow_run(connection_url, run_id)
        if final_run is None or final_run.run_status != "completed":
            raise RuntimeError("Final workflow status is not completed")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            provider_rows = connection.execute(
                """
                SELECT provider_refund_id, request_count
                FROM demo_payment_provider_refunds
                WHERE idempotency_key = %s
                """,
                (refund_idempotency_key(run_id),),
            ).fetchall()
            local_refund = connection.execute(
                """
                SELECT refund_status, provider_refund_id
                FROM refunds
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
            attempts = connection.execute(
                """
                SELECT attempt_number, attempt_status
                FROM refund_attempts
                WHERE refund_id = %s
                ORDER BY attempt_number
                """,
                (refund_result["refund_id"],),
            ).fetchall()
            request = connection.execute(
                """
                SELECT request_status
                FROM return_requests
                WHERE return_request_id = %s
                """,
                (return_request_id,),
            ).fetchone()
            audit = connection.execute(
                """
                SELECT event_type, checkpoint_id
                FROM audit_events
                WHERE run_id = %s AND event_type = 'refund_succeeded'
                """,
                (run_id,),
            ).fetchone()

        if len(provider_rows) != 1 or provider_rows[0]["request_count"] != 2:
            raise RuntimeError("Provider did not preserve exactly one logical refund")
        if local_refund is None or local_refund["refund_status"] != "succeeded":
            raise RuntimeError("Local refund is not successful")
        if str(provider_rows[0]["provider_refund_id"]) != local_refund["provider_refund_id"]:
            raise RuntimeError("Local and provider refund IDs differ")
        if [(row["attempt_number"], row["attempt_status"]) for row in attempts] != [
            (1, "retryable_failure"),
            (2, "succeeded"),
        ]:
            raise RuntimeError(f"Unexpected refund attempt history: {attempts}")
        if request is None or request["request_status"] != "refunded":
            raise RuntimeError("Return request was not marked refunded")
        if audit is None or audit["checkpoint_id"] != turn.checkpoint_id:
            raise RuntimeError("Refund audit event is missing its checkpoint link")

        print("PASS: the provider received two calls with one idempotency key.")
        print("PASS: both calls returned one provider refund ID; no duplicate refund exists.")
        print("PASS: attempt 1 is retryable_failure and attempt 2 succeeded.")
        print("PASS: workflow completed, return request refunded, and audit event recorded.")
        return 0
    finally:
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
                ("40000000-0000-4000-8000-000000000001",),
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
        print(f"Refund smoke test failed: {error}", file=sys.stderr)
        raise
