"""CockroachDB-backed workflow-run ownership and stale-worker fencing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event, Thread
from typing import Literal, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from product_returns.graph_version import CURRENT_GRAPH_VERSION


RunStatus = Literal[
    "ready",
    "running",
    "retry_wait",
    "waiting_for_approval",
    "completed",
    "rejected",
    "failed",
]
ReleasedStatus = Literal[
    "ready",
    "retry_wait",
    "waiting_for_approval",
    "completed",
    "rejected",
    "failed",
]


class GraphVersionMismatch(RuntimeError):
    """Raised when deployed code cannot resume the stored graph version."""


class LeaseLostError(RuntimeError):
    """Raised after a worker loses ownership or cannot renew its lease."""


@dataclass(frozen=True)
class WorkflowRun:
    run_id: UUID
    return_request_id: UUID
    thread_id: str
    run_status: RunStatus
    current_round: str
    next_nodes: list[str]
    latest_checkpoint_id: str | None
    state_version: int
    graph_version: str
    lease_owner: str | None
    lease_generation: int
    lease_acquired_at: datetime | None
    last_heartbeat_at: datetime | None
    lease_expires_at: datetime | None


RUN_COLUMNS = """
    run_id,
    return_request_id,
    thread_id,
    run_status,
    current_round,
    next_nodes,
    latest_checkpoint_id,
    state_version,
    graph_version,
    lease_owner,
    lease_generation,
    lease_acquired_at,
    last_heartbeat_at,
    lease_expires_at
"""


def _connect(connection_url: str) -> psycopg.Connection:
    # Each operation is one atomic autocommit statement, allowing CockroachDB
    # to apply its normal implicit-transaction retry behavior.
    return psycopg.connect(
        connection_url,
        autocommit=True,
        row_factory=dict_row,
    )


def _as_run(row: dict[str, object]) -> WorkflowRun:
    return WorkflowRun(
        run_id=cast(UUID, row["run_id"]),
        return_request_id=cast(UUID, row["return_request_id"]),
        thread_id=cast(str, row["thread_id"]),
        run_status=cast(RunStatus, row["run_status"]),
        current_round=cast(str, row["current_round"]),
        next_nodes=list(cast(list[str], row["next_nodes"])),
        latest_checkpoint_id=cast(str | None, row["latest_checkpoint_id"]),
        state_version=cast(int, row["state_version"]),
        graph_version=cast(str, row["graph_version"]),
        lease_owner=cast(str | None, row["lease_owner"]),
        lease_generation=cast(int, row["lease_generation"]),
        lease_acquired_at=cast(datetime | None, row["lease_acquired_at"]),
        last_heartbeat_at=cast(datetime | None, row["last_heartbeat_at"]),
        lease_expires_at=cast(datetime | None, row["lease_expires_at"]),
    )


def create_workflow_run(
    connection_url: str,
    *,
    return_request_id: UUID,
    thread_id: str,
    run_id: UUID,
    current_round: str = "classification",
    next_nodes: tuple[str, ...] = ("classify_request",),
) -> WorkflowRun:
    """Create a ready run and explicitly stamp the source-owned graph version."""

    with _connect(connection_url) as connection:
        row = connection.execute(
            f"""
            INSERT INTO workflow_runs (
                run_id,
                return_request_id,
                thread_id,
                graph_version,
                current_round,
                next_nodes
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {RUN_COLUMNS}
            """,
            (
                run_id,
                return_request_id,
                thread_id,
                CURRENT_GRAPH_VERSION,
                current_round,
                list(next_nodes),
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("CockroachDB did not return the newly created workflow run")
    return _as_run(row)


def get_workflow_run(connection_url: str, run_id: UUID) -> WorkflowRun | None:
    """Load one workflow run by its distributed UUID primary key."""

    with _connect(connection_url) as connection:
        row = connection.execute(
            f"SELECT {RUN_COLUMNS} FROM workflow_runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    return _as_run(row) if row is not None else None


def langgraph_checkpoint_config(run: WorkflowRun) -> dict[str, dict[str, str]]:
    """Build a resume config pinned to the last application-published checkpoint.

    Workers must not resume from LangGraph's unqualified latest checkpoint:
    a stale worker may have written a later orphan after losing its lease.
    """

    configurable = {"thread_id": run.thread_id}
    if run.latest_checkpoint_id is not None:
        configurable["checkpoint_id"] = run.latest_checkpoint_id
    return {"configurable": configurable}


def claim_workflow_run(
    connection_url: str,
    *,
    run_id: UUID,
    worker_id: str,
    lease_seconds: int,
) -> WorkflowRun | None:
    """Atomically claim runnable work and return its new fencing generation."""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    with _connect(connection_url) as connection:
        row = connection.execute(
            f"""
            UPDATE workflow_runs
            SET
                run_status = 'running',
                next_attempt_at = NULL,
                lease_owner = %s,
                lease_generation = lease_generation + 1,
                lease_acquired_at = now(),
                last_heartbeat_at = now(),
                lease_expires_at = now() + (%s * INTERVAL '1 second'),
                updated_at = now()
            WHERE run_id = %s
              AND graph_version = %s
              AND (
                  run_status = 'ready'
                  OR (
                      run_status = 'retry_wait'
                      AND next_attempt_at <= now()
                  )
                  OR (
                      run_status = 'running'
                      AND lease_expires_at <= now()
                  )
              )
            RETURNING {RUN_COLUMNS}
            """,
            (worker_id, lease_seconds, run_id, CURRENT_GRAPH_VERSION),
        ).fetchone()
    if row is not None:
        return _as_run(row)

    existing = get_workflow_run(connection_url, run_id)
    if existing is not None and existing.graph_version != CURRENT_GRAPH_VERSION:
        raise GraphVersionMismatch(
            f"Run {run_id} uses graph version {existing.graph_version!r}; "
            f"deployed code uses {CURRENT_GRAPH_VERSION!r}"
        )
    return None


def renew_workflow_lease(
    connection_url: str,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    lease_seconds: int,
) -> WorkflowRun | None:
    """Renew only a live lease owned by this exact worker generation."""

    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
    with _connect(connection_url) as connection:
        row = connection.execute(
            f"""
            UPDATE workflow_runs
            SET
                last_heartbeat_at = now(),
                lease_expires_at = now() + (%s * INTERVAL '1 second'),
                updated_at = now()
            WHERE run_id = %s
              AND run_status = 'running'
              AND graph_version = %s
              AND lease_owner = %s
              AND lease_generation = %s
              AND lease_expires_at > now()
            RETURNING {RUN_COLUMNS}
            """,
            (
                lease_seconds,
                run_id,
                CURRENT_GRAPH_VERSION,
                worker_id,
                lease_generation,
            ),
        ).fetchone()
    return _as_run(row) if row is not None else None


def publish_checkpoint(
    connection_url: str,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    expected_state_version: int,
    checkpoint_id: str,
    current_round: str,
    next_nodes: tuple[str, ...],
) -> WorkflowRun | None:
    """Publish a checkpoint only for the current live ownership generation."""

    with _connect(connection_url) as connection:
        row = connection.execute(
            f"""
            UPDATE workflow_runs
            SET
                latest_checkpoint_id = %s,
                state_version = state_version + 1,
                current_round = %s,
                next_nodes = %s,
                updated_at = now()
            WHERE run_id = %s
              AND run_status = 'running'
              AND graph_version = %s
              AND lease_owner = %s
              AND lease_generation = %s
              AND lease_expires_at > now()
              AND state_version = %s
            RETURNING {RUN_COLUMNS}
            """,
            (
                checkpoint_id,
                current_round,
                list(next_nodes),
                run_id,
                CURRENT_GRAPH_VERSION,
                worker_id,
                lease_generation,
                expected_state_version,
            ),
        ).fetchone()
    return _as_run(row) if row is not None else None


def release_workflow_run(
    connection_url: str,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    new_status: ReleasedStatus,
    next_attempt_at: datetime | None = None,
) -> WorkflowRun | None:
    """End current ownership and clear lease fields in one fenced statement."""

    if new_status == "retry_wait" and next_attempt_at is None:
        raise ValueError("retry_wait requires next_attempt_at")
    if new_status != "retry_wait" and next_attempt_at is not None:
        raise ValueError("next_attempt_at is valid only for retry_wait")

    with _connect(connection_url) as connection:
        row = connection.execute(
            f"""
            UPDATE workflow_runs
            SET
                run_status = %s,
                next_attempt_at = %s,
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
            RETURNING {RUN_COLUMNS}
            """,
            (
                new_status,
                next_attempt_at,
                run_id,
                CURRENT_GRAPH_VERSION,
                worker_id,
                lease_generation,
            ),
        ).fetchone()
    return _as_run(row) if row is not None else None


class LeaseHeartbeat:
    """Renew a claimed run in a daemon thread while graph work executes."""

    def __init__(
        self,
        connection_url: str,
        lease: WorkflowRun,
        *,
        interval_seconds: float,
        lease_seconds: int,
    ) -> None:
        if lease.run_status != "running" or lease.lease_owner is None:
            raise ValueError("LeaseHeartbeat requires a claimed running workflow")
        if interval_seconds <= 0 or interval_seconds >= lease_seconds:
            raise ValueError(
                "interval_seconds must be positive and shorter than lease_seconds"
            )
        self._connection_url = connection_url
        self._run_id = lease.run_id
        self._worker_id = lease.lease_owner
        self._generation = lease.lease_generation
        self._interval_seconds = interval_seconds
        self._lease_seconds = lease_seconds
        self._stop = Event()
        self._lost = Event()
        self._error: BaseException | None = None
        self._thread = Thread(
            target=self._run,
            name=f"workflow-heartbeat-{lease.run_id}",
            daemon=True,
        )

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                renewed = renew_workflow_lease(
                    self._connection_url,
                    run_id=self._run_id,
                    worker_id=self._worker_id,
                    lease_generation=self._generation,
                    lease_seconds=self._lease_seconds,
                )
                if renewed is None:
                    self._lost.set()
                    return
            except BaseException as error:  # surfaced to the owning worker
                self._error = error
                self._lost.set()
                return

    def start(self) -> "LeaseHeartbeat":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self._interval_seconds * 2))

    def raise_if_lost(self) -> None:
        if self._lost.is_set():
            detail = f": {self._error}" if self._error is not None else ""
            raise LeaseLostError(
                f"Workflow lease was lost for run {self._run_id}{detail}"
            ) from self._error

    def __enter__(self) -> "LeaseHeartbeat":
        return self.start()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()
        if exc_type is None:
            self.raise_if_lost()

