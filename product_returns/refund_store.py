"""Atomic publication of a successfully checkpointed refund outcome."""

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
from product_returns.reservation import finalize_return_reservations
from product_returns.state import RefundResult, ReturnDecision
from product_returns.workflow_runs import LeaseLostError, WorkflowRun


@dataclass(frozen=True)
class RefundCompletionResult:
    run_id: UUID
    run_status: str
    return_request_status: str
    state_version: int
    audit_sequence_number: int


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def commit_refund_completion(
    connection_url: str,
    *,
    lease: WorkflowRun,
    refund_result: RefundResult,
    decision: ReturnDecision,
    checkpoint_id: str,
    max_attempts: int = 5,
) -> RefundCompletionResult:
    """Fence and atomically finalize the workflow, request, and audit trail."""

    if lease.run_status != "running" or lease.lease_owner is None:
        raise ValueError("Refund completion requires a currently claimed run")
    if lease.latest_checkpoint_id != checkpoint_id:
        raise ValueError("Refund checkpoint is not the run's published checkpoint")
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            run_status = 'completed',
                            current_round = 'completed',
                            next_nodes = ARRAY[]::STRING[],
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
                            "Refund completion lost its ownership/checkpoint fence"
                        )

                    verified_refund = connection.execute(
                        """
                        SELECT refund_id
                        FROM refunds
                        WHERE run_id = %s
                          AND refund_id = %s
                          AND idempotency_key = %s
                          AND refund_status = 'succeeded'
                          AND provider_refund_id = %s
                        """,
                        (
                            lease.run_id,
                            UUID(refund_result["refund_id"]),
                            refund_result["idempotency_key"],
                            refund_result["provider_refund_id"],
                        ),
                    ).fetchone()
                    if verified_refund is None:
                        raise RuntimeError("Published checkpoint has no matching successful refund")

                    finalized_items = finalize_return_reservations(
                        connection,
                        cast(UUID, workflow["return_request_id"]),
                    )
                    if finalized_items < 1:
                        raise RuntimeError(
                            "Successful refund has no reserved return-item quantity"
                        )

                    updated_request = connection.execute(
                        """
                        UPDATE return_requests
                        SET request_status = 'refunded', updated_at = now()
                        WHERE return_request_id = %s
                        RETURNING return_request_id
                        """,
                        (workflow["return_request_id"],),
                    ).fetchone()
                    if updated_request is None:
                        raise RuntimeError("Refund's return request no longer exists")

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
                            run_id, sequence_number, event_type, node_name,
                            actor_type, actor_id, checkpoint_id, event_data
                        ) VALUES (
                            %s, %s, 'refund_succeeded', 'issue_refund',
                            'payment_provider', %s, %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence_number,
                            refund_result["payment_provider"],
                            checkpoint_id,
                            Jsonb(
                                {
                                    "refund": refund_result,
                                    "decision": decision,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                    "state_version": new_state_version,
                                    "workflow_status": "completed",
                                    "return_request_status": "refunded",
                                    "finalized_return_item_count": finalized_items,
                                }
                            ),
                        ),
                    )

                return RefundCompletionResult(
                    run_id=lease.run_id,
                    run_status="completed",
                    return_request_status="refunded",
                    state_version=new_state_version,
                    audit_sequence_number=sequence_number,
                )
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)

    raise AssertionError("Unreachable transaction retry state")
