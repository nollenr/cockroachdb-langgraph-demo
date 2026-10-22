"""Atomically persist an accepted return decision and its audit explanation."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from time import sleep
from typing import cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from product_returns.graph_version import CURRENT_GRAPH_VERSION
from product_returns.state import ReturnDecision
from product_returns.workflow_runs import LeaseLostError, WorkflowRun


@dataclass(frozen=True)
class DecisionCommitResult:
    run_id: UUID
    run_status: str
    return_request_status: str
    state_version: int
    audit_sequence_number: int
    approval_request_id: UUID | None


def _transition(decision: ReturnDecision) -> tuple[str, str, str, list[str], str]:
    outcome = decision["outcome"]
    if outcome == "ineligible":
        return "rejected", "rejected", "decision", [], "return_rejected"
    if outcome == "requires_approval":
        return (
            "waiting_for_approval",
            "pending_approval",
            "approval",
            ["await_manager_approval"],
            "manager_approval_requested",
        )
    if outcome == "approved_for_refund":
        return "ready", "approved", "refund", ["issue_refund"], "refund_approved"
    raise ValueError(f"Unsupported decision outcome: {outcome!r}")


def commit_return_decision(
    connection_url: str,
    *,
    lease: WorkflowRun,
    decision: ReturnDecision,
    checkpoint_id: str,
    max_attempts: int = 5,
) -> DecisionCommitResult:
    """Commit workflow, business status, approval, and audit facts atomically."""

    if lease.run_status != "running" or lease.lease_owner is None:
        raise ValueError("Decision commit requires a currently claimed run")
    if lease.latest_checkpoint_id != checkpoint_id:
        raise ValueError("Decision checkpoint is not the run's published checkpoint")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    (
        run_status,
        request_status,
        current_round,
        next_nodes,
        event_type,
    ) = _transition(decision)

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    transitioned = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            run_status = %s,
                            current_round = %s,
                            next_nodes = %s,
                            state_version = state_version + 1,
                            next_attempt_at = NULL,
                            lease_owner = NULL,
                            lease_acquired_at = NULL,
                            last_heartbeat_at = NULL,
                            lease_expires_at = NULL,
                            updated_at = now()
                        WHERE run_id = %s
                          AND run_status = 'running'
                          AND graph_version = %s
                          AND lease_owner = %s
                          AND lease_generation = %s
                          AND lease_expires_at > now()
                          AND state_version = %s
                          AND latest_checkpoint_id = %s
                        RETURNING return_request_id, state_version
                        """,
                        (
                            run_status,
                            current_round,
                            next_nodes,
                            lease.run_id,
                            CURRENT_GRAPH_VERSION,
                            lease.lease_owner,
                            lease.lease_generation,
                            lease.state_version,
                            checkpoint_id,
                        ),
                    ).fetchone()
                    if transitioned is None:
                        raise LeaseLostError(
                            "Decision commit lost its lease, checkpoint, or state-version fence"
                        )

                    return_request_id = cast(UUID, transitioned["return_request_id"])
                    new_state_version = cast(int, transitioned["state_version"])
                    updated_request = connection.execute(
                        """
                        UPDATE return_requests
                        SET request_status = %s, updated_at = now()
                        WHERE return_request_id = %s
                        RETURNING return_request_id
                        """,
                        (request_status, return_request_id),
                    ).fetchone()
                    if updated_request is None:
                        raise RuntimeError("Decision's return request no longer exists")

                    approval_request_id: UUID | None = None
                    if decision["outcome"] == "requires_approval":
                        if decision["currency"] is None:
                            raise ValueError("Manager approval requires a currency")
                        approval = connection.execute(
                            """
                            INSERT INTO approval_requests (
                                run_id,
                                request_number,
                                refund_amount,
                                currency,
                                approval_reason
                            ) VALUES (%s, 1, %s, %s, %s)
                            RETURNING approval_request_id
                            """,
                            (
                                lease.run_id,
                                Decimal(decision["calculated_refund_amount"]),
                                decision["currency"],
                                decision["explanation"],
                            ),
                        ).fetchone()
                        if approval is None:
                            raise RuntimeError("Approval request was not created")
                        approval_request_id = cast(UUID, approval["approval_request_id"])

                    sequence_row = connection.execute(
                        """
                        SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
                        FROM audit_events
                        WHERE run_id = %s
                        """,
                        (lease.run_id,),
                    ).fetchone()
                    if sequence_row is None:
                        raise RuntimeError("Could not allocate audit sequence number")
                    sequence_number = cast(int, sequence_row["next_sequence"])

                    event_data = {
                        "decision": decision,
                        "graph_version": CURRENT_GRAPH_VERSION,
                        "lease_generation": lease.lease_generation,
                        "state_version": new_state_version,
                        "return_request_status": request_status,
                        "workflow_status": run_status,
                    }
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id,
                            sequence_number,
                            event_type,
                            node_name,
                            actor_type,
                            checkpoint_id,
                            event_data
                        ) VALUES (%s, %s, %s, 'decide_return', 'system', %s, %s)
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence_number,
                            event_type,
                            checkpoint_id,
                            Jsonb(event_data),
                        ),
                    )

                return DecisionCommitResult(
                    run_id=lease.run_id,
                    run_status=run_status,
                    return_request_status=request_status,
                    state_version=new_state_version,
                    audit_sequence_number=sequence_number,
                    approval_request_id=approval_request_id,
                )
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            base_delay = min(0.05 * (2**attempt), 0.8)
            sleep(base_delay + random.uniform(0, base_delay))

    raise AssertionError("Unreachable transaction retry state")
