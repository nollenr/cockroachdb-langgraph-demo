"""Atomic terminal commit for an unavailable return quantity."""

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
from product_returns.state import ReturnReservationResult
from product_returns.workflow_runs import LeaseLostError, WorkflowRun


@dataclass(frozen=True)
class ReservationConflictCommitResult:
    run_id: UUID
    run_status: str
    return_request_status: str
    state_version: int
    audit_sequence_number: int


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def commit_reservation_conflict(
    connection_url: str,
    *,
    lease: WorkflowRun,
    reservation: ReturnReservationResult,
    checkpoint_id: str,
    max_attempts: int = 5,
) -> ReservationConflictCommitResult:
    """Persist a quantity conflict as an explained business rejection."""

    if reservation["status"] != "conflict":
        raise ValueError("Reservation-conflict commit requires a conflict result")
    if lease.run_status != "running" or lease.lease_owner is None:
        raise ValueError("Reservation conflict requires a currently claimed run")
    if lease.latest_checkpoint_id != checkpoint_id:
        raise ValueError("Reservation checkpoint is not the published checkpoint")

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET
                            run_status = 'rejected',
                            current_round = 'reservation',
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
                            "Reservation conflict lost its ownership/checkpoint fence"
                        )
                    return_request_id = cast(UUID, workflow["return_request_id"])
                    release_return_reservations(connection, return_request_id)
                    connection.execute(
                        """
                        UPDATE return_requests
                        SET request_status = 'rejected', updated_at = now()
                        WHERE return_request_id = %s
                        RETURNING NOTHING
                        """,
                        (return_request_id,),
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
                    state_version = cast(int, workflow["state_version"])
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id, sequence_number, event_type, node_name,
                            actor_type, checkpoint_id, event_data
                        ) VALUES (
                            %s, %s, 'return_quantity_unavailable',
                            'reserve_return_items', 'system', %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence_number,
                            checkpoint_id,
                            Jsonb(
                                {
                                    "reservation": reservation,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                    "state_version": state_version,
                                    "workflow_status": "rejected",
                                    "return_request_status": "rejected",
                                }
                            ),
                        ),
                    )
                return ReservationConflictCommitResult(
                    run_id=lease.run_id,
                    run_status="rejected",
                    return_request_status="rejected",
                    state_version=state_version,
                    audit_sequence_number=sequence_number,
                )
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)

    raise AssertionError("Unreachable transaction retry state")
