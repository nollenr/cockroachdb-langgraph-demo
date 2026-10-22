#!/usr/bin/env python3
"""Verify atomic decision routing and audit persistence in CockroachDB."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.decision_store import commit_return_decision  # noqa: E402
from product_returns.graph_version import validate_graph_definition  # noqa: E402
from product_returns.state import ReturnDecision  # noqa: E402
from product_returns.workflow_runs import (  # noqa: E402
    claim_workflow_run,
    create_workflow_run,
    publish_checkpoint,
)


EXPECTED_DATABASE = "product_returns"
EXPECTED_RUNTIME_USER = "product_returns_app"
CUSTOMER_ID = UUID("10000000-0000-4000-8000-000000000002")
ORDER_ID = UUID("30000000-0000-4000-8000-000000000005")


def validated_app_url() -> str:
    connection_url = os.environ.get("CRDB_APP_URL")
    if not connection_url:
        raise RuntimeError("Required environment variable CRDB_APP_URL is not set")
    parsed = urlparse(connection_url)
    if parsed.username != EXPECTED_RUNTIME_USER:
        raise RuntimeError(
            f"CRDB_APP_URL must use {EXPECTED_RUNTIME_USER!r}, not an owner identity"
        )
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"CRDB_APP_URL must target {EXPECTED_DATABASE!r}")
    return connection_url


def citation(clause_key: str, heading: str) -> dict[str, object]:
    return {
        "document_title": "Standard Return and Refund Policy",
        "policy_key": "standard-returns",
        "policy_version": "1.0",
        "section_heading": heading,
        "clause_key": clause_key,
        "source_uri": "policies/standard-return-policy-v1.md",
        "content_sha256": "decision-store-smoke-test",
        "quote": f"Verified policy text for {clause_key}.",
        "distance_score": 0.1,
    }


def decision(
    *,
    outcome: str,
    reason_code: str,
    explanation: str,
    amount: str,
    citations: list[dict[str, object]],
) -> ReturnDecision:
    requires_approval = outcome == "requires_approval"
    return {
        "outcome": outcome,
        "next_action": (
            "wait_for_manager_approval"
            if requires_approval
            else "finish_without_refund"
        ),
        "eligible": requires_approval,
        "requires_manager_approval": requires_approval,
        "reason_codes": [reason_code],
        "explanation": explanation,
        "calculated_refund_amount": amount,
        "approved_refund_amount": None,
        "currency": "USD",
        "policy_citations": citations,
        "facts": {
            "order_number": "DEMO-1005",
            "days_since_order": 45 if outcome == "ineligible" else 8,
            "return_window_days": 30,
            "manager_threshold": "500.00",
        },
    }  # type: ignore[return-value]


def create_claim_and_publish(
    connection_url: str,
    *,
    return_request_id: UUID,
    run_id: UUID,
    thread_id: str,
    checkpoint_id: str,
):
    create_workflow_run(
        connection_url,
        return_request_id=return_request_id,
        thread_id=thread_id,
        run_id=run_id,
    )
    claimed = claim_workflow_run(
        connection_url,
        run_id=run_id,
        worker_id=f"decision-store-smoke-{uuid4()}",
        lease_seconds=30,
    )
    if claimed is None or claimed.lease_owner is None:
        raise RuntimeError("Could not claim decision-store smoke-test run")
    published = publish_checkpoint(
        connection_url,
        run_id=run_id,
        worker_id=claimed.lease_owner,
        lease_generation=claimed.lease_generation,
        expected_state_version=claimed.state_version,
        checkpoint_id=checkpoint_id,
        current_round="decision",
        next_nodes=(),
    )
    if published is None:
        raise RuntimeError("Could not publish decision-store smoke-test checkpoint")
    return published


def run_case(
    connection_url: str,
    *,
    name: str,
    expected_run_status: str,
    expected_request_status: str,
    expected_round: str,
    expected_next_nodes: list[str],
    expected_event_type: str,
    expected_reason: str,
    return_decision: ReturnDecision,
    expect_approval: bool,
) -> None:
    return_request_id = uuid4()
    run_id = uuid4()
    thread_id = f"decision-store-{uuid4()}"
    checkpoint_id = f"decision-checkpoint-{uuid4()}"

    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO return_requests (
                return_request_id,
                customer_id,
                order_id,
                request_text,
                classified_intent,
                request_status
            ) VALUES (%s, %s, %s, %s, 'refund', 'gathering_evidence')
            RETURNING NOTHING
            """,
            (return_request_id, CUSTOMER_ID, ORDER_ID, f"{name} smoke test"),
        )

    try:
        published = create_claim_and_publish(
            connection_url,
            return_request_id=return_request_id,
            run_id=run_id,
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
        )
        committed = commit_return_decision(
            connection_url,
            lease=published,
            decision=return_decision,
            checkpoint_id=checkpoint_id,
        )
        if committed.state_version != 2:
            raise RuntimeError(f"{name}: expected state version 2")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT
                    wr.run_status,
                    wr.current_round,
                    wr.next_nodes,
                    wr.latest_checkpoint_id,
                    wr.state_version,
                    wr.lease_owner,
                    rr.request_status,
                    ae.event_type,
                    ae.node_name,
                    ae.checkpoint_id,
                    ae.event_data,
                    ar.approval_request_id,
                    ar.approval_status,
                    ar.refund_amount
                FROM workflow_runs AS wr
                JOIN return_requests AS rr
                    ON rr.return_request_id = wr.return_request_id
                JOIN audit_events AS ae
                    ON ae.run_id = wr.run_id
                LEFT JOIN approval_requests AS ar
                    ON ar.run_id = wr.run_id
                WHERE wr.run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError(f"{name}: persisted decision rows were not found")
        if row["run_status"] != expected_run_status:
            raise RuntimeError(f"{name}: wrong workflow status {row['run_status']}")
        if row["request_status"] != expected_request_status:
            raise RuntimeError(f"{name}: wrong request status {row['request_status']}")
        if row["current_round"] != expected_round:
            raise RuntimeError(f"{name}: wrong current round {row['current_round']}")
        if row["next_nodes"] != expected_next_nodes:
            raise RuntimeError(f"{name}: wrong next nodes {row['next_nodes']}")
        if row["latest_checkpoint_id"] != checkpoint_id or row["state_version"] != 2:
            raise RuntimeError(f"{name}: checkpoint/state version was not preserved")
        if row["lease_owner"] is not None:
            raise RuntimeError(f"{name}: decision commit did not release the lease")
        if row["event_type"] != expected_event_type or row["node_name"] != "decide_return":
            raise RuntimeError(f"{name}: wrong audit event identity")
        if row["checkpoint_id"] != checkpoint_id:
            raise RuntimeError(f"{name}: audit event has the wrong checkpoint")
        stored_decision = row["event_data"]["decision"]
        if expected_reason not in stored_decision["reason_codes"]:
            raise RuntimeError(f"{name}: exact decision reason was not audited")
        if not stored_decision["policy_citations"]:
            raise RuntimeError(f"{name}: policy citations were not audited")
        has_approval = row["approval_request_id"] is not None
        if has_approval != expect_approval:
            raise RuntimeError(f"{name}: approval-row expectation was not met")
        if expect_approval and row["approval_status"] != "pending":
            raise RuntimeError(f"{name}: approval row is not pending")

        print(
            f"PASS {name}: {expected_run_status}, {expected_event_type}, "
            f"reason={expected_reason}, checkpoint={checkpoint_id}."
        )
    finally:
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute("DELETE FROM audit_events WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM approval_requests WHERE run_id = %s", (run_id,)
            )
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = %s",
                (return_request_id,),
            )


def main() -> int:
    validate_graph_definition()
    connection_url = validated_app_url()

    run_case(
        connection_url,
        name="outside_window_rejection",
        expected_run_status="rejected",
        expected_request_status="rejected",
        expected_round="decision",
        expected_next_nodes=[],
        expected_event_type="return_rejected",
        expected_reason="OUTSIDE_RETURN_WINDOW",
        return_decision=decision(
            outcome="ineligible",
            reason_code="OUTSIDE_RETURN_WINDOW",
            explanation="The purchase is outside the 30-day return window.",
            amount="140.39",
            citations=[
                citation("RET-ELIGIBILITY-001", "Return Eligibility and Time Window")
            ],
        ),
        expect_approval=False,
    )
    run_case(
        connection_url,
        name="manager_approval_wait",
        expected_run_status="waiting_for_approval",
        expected_request_status="pending_approval",
        expected_round="approval",
        expected_next_nodes=["await_manager_approval"],
        expected_event_type="manager_approval_requested",
        expected_reason="REFUND_OVER_MANAGER_LIMIT",
        return_decision=decision(
            outcome="requires_approval",
            reason_code="REFUND_OVER_MANAGER_LIMIT",
            explanation="The calculated refund is greater than the $500 manager threshold.",
            amount="700.92",
            citations=[
                citation("RET-APPROVAL-001", "Manual Review and Manager Approval"),
                citation("RET-AMOUNT-001", "Refund Amount"),
            ],
        ),
        expect_approval=True,
    )
    print("Atomic decision-store smoke test passed 2/2 scenarios.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Decision-store smoke test failed: {error}", file=sys.stderr)
        raise
