"""Durable node-attempt events used by the customer presentation API."""

from __future__ import annotations

from time import perf_counter
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class CockroachNodeEventRecorder:
    """Persist each node attempt independently from workflow business commits."""

    def __init__(self, connection_url: str) -> None:
        self._connection_url = connection_url
        self._started: dict[UUID, float] = {}

    def started(self, node_name: str, safe_input: Any) -> UUID:
        run_id = safe_input.get("run_id") if isinstance(safe_input, dict) else None
        if not run_id:
            raise ValueError(f"Node {node_name!r} has no run_id for progress recording")
        with psycopg.connect(
            self._connection_url,
            autocommit=True,
            row_factory=dict_row,
        ) as connection:
            row = connection.execute(
                """
                INSERT INTO node_attempts (
                    run_id, node_name, attempt_number,
                    attempt_status, input_state
                )
                SELECT
                    %s, %s, COALESCE(max(attempt_number), 0) + 1,
                    'started', %s
                FROM node_attempts
                WHERE run_id = %s
                  AND node_name = %s
                RETURNING node_attempt_id
                """,
                (
                    UUID(str(run_id)),
                    node_name,
                    Jsonb(safe_input),
                    UUID(str(run_id)),
                    node_name,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("CockroachDB did not return the node event ID")
        event_id = row["node_attempt_id"]
        self._started[event_id] = perf_counter()
        return event_id

    def succeeded(self, event_id: UUID, safe_output: Any) -> None:
        self._complete(event_id, "succeeded", safe_output=safe_output)

    def failed(self, event_id: UUID, error: Exception) -> None:
        status = "retryable_failure" if getattr(error, "retryable", False) else "failed"
        self._complete(event_id, status, error=error)

    def _complete(
        self,
        event_id: UUID,
        status: str,
        *,
        safe_output: Any | None = None,
        error: Exception | None = None,
    ) -> None:
        started = self._started.pop(event_id, None)
        duration_ms = max(0, round((perf_counter() - started) * 1000)) if started else None
        with psycopg.connect(self._connection_url, autocommit=True) as connection:
            updated = connection.execute(
                """
                UPDATE node_attempts
                SET attempt_status = %s,
                    output_summary = %s,
                    error_code = %s,
                    error_message = %s,
                    finished_at = now(),
                    duration_ms = %s
                WHERE node_attempt_id = %s
                  AND attempt_status = 'started'
                RETURNING node_attempt_id
                """,
                (
                    status,
                    Jsonb(safe_output) if safe_output is not None else None,
                    type(error).__name__ if error is not None else None,
                    str(error) if error is not None else None,
                    duration_ms,
                    event_id,
                ),
            ).fetchone()
        if updated is None:
            raise RuntimeError(f"Node event {event_id} was not in running state")
