"""Atomic manager decisions and post-resume workflow transitions."""

from __future__ import annotations

import random
from dataclasses import dataclass
from time import sleep
from typing import cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from product_returns.graph_version import CURRENT_GRAPH_VERSION
from product_returns.reservation import release_return_reservations
from product_returns.state import ManagerDecision
from product_returns.workflow_runs import LeaseLostError, WorkflowRun


@dataclass(frozen=True)
class RecordedManagerDecision:
    run_id: UUID
    approval_request_id: UUID
    checkpoint_id: str
    state_version: int
    resume_value: ManagerDecision


@dataclass(frozen=True)
class ApprovalResolutionResult:
    run_id: UUID
    run_status: str
    return_request_status: str
    state_version: int
    audit_sequence_number: int


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def record_manager_decision(
    connection_url: str,
    *,
    run_id: UUID,
    decision: str,
    decided_by: str,
    decision_note: str | None,
    max_attempts: int = 5,
) -> RecordedManagerDecision:
    """Record one pending approval response and make its graph resumable."""

    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    if not decided_by.strip():
        raise ValueError("decided_by must not be empty")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    approval = connection.execute(
                        """
                        UPDATE approval_requests
                        SET
                            approval_status = %s,
                            decided_at = now(),
                            decided_by = %s,
                            decision_note = %s
                        WHERE run_id = %s
                          AND approval_status = 'pending'
                        RETURNING approval_request_id, decided_at
                        """,
                        (decision, decided_by.strip(), decision_note, run_id),
                    ).fetchone()
                    if approval is None:
                        raise RuntimeError(
                            "No pending manager approval exists for this run"
                        )

                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            run_status = 'ready',
                            current_round = 'approval_resume',
                            state_version = state_version + 1,
                            updated_at = now()
                        WHERE run_id = %s
                          AND run_status = 'waiting_for_approval'
                          AND graph_version = %s
                          AND latest_checkpoint_id IS NOT NULL
                          AND next_nodes @> ARRAY['await_manager_approval']::STRING[]
                        RETURNING latest_checkpoint_id, state_version
                        """,
                        (run_id, CURRENT_GRAPH_VERSION),
                    ).fetchone()
                    if workflow is None:
                        raise RuntimeError(
                            "Workflow is not waiting at its manager-approval checkpoint"
                        )

                    sequence = connection.execute(
                        """
                        SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
                        FROM audit_events
                        WHERE run_id = %s
                        """,
                        (run_id,),
                    ).fetchone()
                    if sequence is None:
                        raise RuntimeError("Could not allocate audit sequence number")

                    decided_at = approval["decided_at"]
                    resume_value: ManagerDecision = {
                        "decision": decision,  # type: ignore[typeddict-item]
                        "decided_by": decided_by.strip(),
                        "decision_note": decision_note,
                        "decided_at": decided_at.isoformat(),
                    }
                    sequence_number = cast(int, sequence["next_sequence"])
                    checkpoint_id = cast(str, workflow["latest_checkpoint_id"])
                    new_state_version = cast(int, workflow["state_version"])
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id,
                            sequence_number,
                            event_type,
                            node_name,
                            actor_type,
                            actor_id,
                            checkpoint_id,
                            event_data
                        ) VALUES (
                            %s, %s, %s, 'await_manager_approval', 'manager',
                            %s, %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            run_id,
                            sequence_number,
                            f"manager_{decision}",
                            decided_by.strip(),
                            checkpoint_id,
                            Jsonb(
                                {
                                    "manager_decision": resume_value,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                    "state_version": new_state_version,
                                }
                            ),
                        ),
                    )

                return RecordedManagerDecision(
                    run_id=run_id,
                    approval_request_id=cast(UUID, approval["approval_request_id"]),
                    checkpoint_id=checkpoint_id,
                    state_version=new_state_version,
                    resume_value=resume_value,
                )
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)

    raise AssertionError("Unreachable transaction retry state")


def load_manager_resume_value(
    connection_url: str,
    *,
    run_id: UUID,
) -> ManagerDecision:
    """Load the durable response supplied to LangGraph's Command(resume=...)."""

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT approval_status, decided_by, decision_note, decided_at
            FROM approval_requests
            WHERE run_id = %s
              AND approval_status IN ('approved', 'rejected')
            ORDER BY request_number DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Run has no recorded manager decision to resume")
    return {
        "decision": row["approval_status"],
        "decided_by": row["decided_by"],
        "decision_note": row["decision_note"],
        "decided_at": row["decided_at"].isoformat(),
    }


def commit_approval_resolution(
    connection_url: str,
    *,
    lease: WorkflowRun,
    manager_decision: ManagerDecision,
    checkpoint_id: str,
    max_attempts: int = 5,
) -> ApprovalResolutionResult:
    """Commit the terminal rejection or queue an approved return for refund."""

    if lease.run_status != "running" or lease.lease_owner is None:
        raise ValueError("Approval resolution requires a currently claimed run")
    if lease.latest_checkpoint_id != checkpoint_id:
        raise ValueError("Resolution checkpoint is not the published checkpoint")
    approved = manager_decision["decision"] == "approved"
    run_status = "ready" if approved else "rejected"
    request_status = "approved" if approved else "rejected"
    current_round = "refund" if approved else "approval"
    next_nodes = ["issue_refund"] if approved else []
    event_type = "manager_approval_applied" if approved else "return_rejected_by_manager"

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            run_status = %s,
                            current_round = %s,
                            next_nodes = %s,
                            state_version = state_version + 1,
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
                    if workflow is None:
                        raise LeaseLostError(
                            "Approval resolution lost its ownership/checkpoint fence"
                        )

                    if not approved:
                        release_return_reservations(
                            connection,
                            cast(UUID, workflow["return_request_id"]),
                        )

                    connection.execute(
                        """
                        UPDATE return_requests
                        SET request_status = %s, updated_at = now()
                        WHERE return_request_id = %s
                        RETURNING NOTHING
                        """,
                        (request_status, workflow["return_request_id"]),
                    )
                    sequence = connection.execute(
                        """
                        SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
                        FROM audit_events
                        WHERE run_id = %s
                        """,
                        (lease.run_id,),
                    ).fetchone()
                    if sequence is None:
                        raise RuntimeError("Could not allocate audit sequence number")
                    sequence_number = cast(int, sequence["next_sequence"])
                    new_state_version = cast(int, workflow["state_version"])
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id,
                            sequence_number,
                            event_type,
                            node_name,
                            actor_type,
                            actor_id,
                            checkpoint_id,
                            event_data
                        ) VALUES (
                            %s, %s, %s, 'await_manager_approval', 'manager',
                            %s, %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence_number,
                            event_type,
                            manager_decision["decided_by"],
                            checkpoint_id,
                            Jsonb(
                                {
                                    "manager_decision": manager_decision,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                    "state_version": new_state_version,
                                    "workflow_status": run_status,
                                    "return_request_status": request_status,
                                }
                            ),
                        ),
                    )

                return ApprovalResolutionResult(
                    run_id=lease.run_id,
                    run_status=run_status,
                    return_request_status=request_status,
                    state_version=new_state_version,
                    audit_sequence_number=sequence_number,
                )
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)

    raise AssertionError("Unreachable transaction retry state")
