"""Durable, demo-only one-shot failure injection and manual recovery."""

from __future__ import annotations

import random
from collections.abc import Callable
from time import sleep
from typing import Any, TypeVar
from uuid import UUID

import psycopg
from prometheus_client import Counter
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from product_returns.graph_version import CURRENT_GRAPH_VERSION
from product_returns.refund import PreparedRefund, ProviderRefund
from product_returns.state import ReturnWorkflowState
from product_returns.workflow_runs import LeaseLostError, WorkflowRun


FailureNode = str
NodeResult = TypeVar("NodeResult")
ALLOWED_FAILURE_NODES = frozenset(
    {"lookup_order", "retrieve_policy", "assess_fraud", "issue_refund"}
)
INJECTED_FAILURES = Counter(
    "product_returns_injected_failures_total",
    "Presenter-injected one-shot workflow failures.",
    ["node"],
)
RECOVERY_RESUMPTIONS = Counter(
    "product_returns_workflow_resumptions_total",
    "Presenter-requested workflow resumptions.",
    ["reason"],
)
RECOVERY_CHECKPOINTS = Counter(
    "product_returns_checkpoint_recoveries_total",
    "Recovery checkpoints published after controlled failures.",
)


class InjectedDemoFailure(RuntimeError):
    """A deliberate, one-shot failure that must wait for presenter recovery."""

    retryable = True

    def __init__(self, node_name: str, evidence: dict[str, Any] | None = None) -> None:
        self.node_name = node_name
        self.evidence = evidence or {}
        super().__init__(
            f"Presenter injected a one-shot failure at node {node_name!r}"
        )


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def inject_failure_once(
    connection_url: str,
    node_name: str,
    node: Callable[[ReturnWorkflowState], NodeResult],
) -> Callable[[ReturnWorkflowState], NodeResult]:
    """Wrap a node with one durable compare-and-set synthetic failure."""

    if node_name not in ALLOWED_FAILURE_NODES - {"issue_refund"}:
        raise ValueError(f"Unsupported failure-injection node {node_name!r}")

    def wrapped(state: ReturnWorkflowState) -> NodeResult:
        run_id = UUID(str(state["run_id"]))
        with psycopg.connect(
            connection_url,
            autocommit=True,
            row_factory=dict_row,
        ) as connection:
            triggered = connection.execute(
                """
                UPDATE workflow_failure_injections
                SET injection_status = 'triggered', triggered_at = now()
                WHERE run_id = %s
                  AND node_name = %s
                  AND injection_status = 'planned'
                RETURNING run_id
                """,
                (run_id, node_name),
            ).fetchone()
        if triggered is not None:
            INJECTED_FAILURES.labels(node=node_name).inc()
            raise InjectedDemoFailure(node_name)
        return node(state)

    return wrapped


def inject_payment_failure_once(
    connection_url: str,
    prepared: PreparedRefund,
    provider: ProviderRefund,
) -> None:
    """Stop after the provider ledger commits, before local refund completion."""

    with psycopg.connect(connection_url, autocommit=True, row_factory=dict_row) as connection:
        triggered = connection.execute(
            """
            UPDATE workflow_failure_injections
            SET injection_status = 'triggered', triggered_at = now()
            WHERE run_id = %s
              AND node_name = 'issue_refund'
              AND failure_mode = 'fail_once_after_provider_success'
              AND injection_status = 'planned'
            RETURNING run_id
            """,
            (prepared.run_id,),
        ).fetchone()
    if triggered is not None:
        INJECTED_FAILURES.labels(node="issue_refund").inc()
        raise InjectedDemoFailure(
            "issue_refund",
            {
                "idempotency_key": prepared.idempotency_key,
                "provider_refund_id": str(provider.provider_refund_id),
                "provider_request_count": provider.provider_request_count,
                "provider_succeeded": True,
                "local_refund_completed": False,
            },
        )


def pause_for_injected_failure(
    connection_url: str,
    *,
    lease: WorkflowRun,
    published: WorkflowRun,
    checkpoint_id: str,
    failure: InjectedDemoFailure,
    max_attempts: int = 5,
) -> WorkflowRun:
    """Release ownership and durably pause until the presenter requests resume."""

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    preserved_rows = connection.execute(
                        """
                        SELECT DISTINCT node_name
                        FROM node_attempts
                        WHERE run_id = %s
                          AND attempt_status = 'succeeded'
                        ORDER BY node_name
                        """,
                        (lease.run_id,),
                    ).fetchall()
                    preserved_nodes = [str(row["node_name"]) for row in preserved_rows]

                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET run_status = 'retry_wait',
                            current_round = 'recovery_paused',
                            next_nodes = ARRAY[%s]::STRING[],
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
                          AND state_version = %s
                          AND latest_checkpoint_id = %s
                        RETURNING run_id, return_request_id, thread_id,
                                  run_status, current_round, next_nodes,
                                  latest_checkpoint_id, state_version,
                                  graph_version, lease_owner, lease_generation,
                                  lease_acquired_at, last_heartbeat_at,
                                  lease_expires_at
                        """,
                        (
                            failure.node_name,
                            lease.run_id,
                            CURRENT_GRAPH_VERSION,
                            lease.lease_owner,
                            lease.lease_generation,
                            published.state_version,
                            checkpoint_id,
                        ),
                    ).fetchone()
                    if workflow is None:
                        raise LeaseLostError(
                            "Injected-failure pause lost its lease fence"
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
                        raise RuntimeError("Could not allocate recovery audit sequence")
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id, sequence_number, event_type, node_name,
                            actor_type, checkpoint_id, event_data
                        ) VALUES (
                            %s, %s, 'injected_failure_paused', %s,
                            'system', %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence["next_sequence"],
                            failure.node_name,
                            checkpoint_id,
                            Jsonb(
                                {
                                    "failure_injected": True,
                                    "failure_code": "INJECTED_DEMO_FAILURE",
                                    "preserved_nodes": preserved_nodes,
                                    "retry_nodes": [failure.node_name],
                                    "lease_generation": lease.lease_generation,
                                    "lease_released": True,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                    "state_version": published.state_version,
                                    "provider_evidence": failure.evidence,
                                }
                            ),
                        ),
                    )
                RECOVERY_CHECKPOINTS.inc()
                return WorkflowRun(**dict(workflow))
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")


def request_recovery_resume(
    connection_url: str,
    *,
    run_id: UUID,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Make exactly one manually paused synthetic failure claimable again."""

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    injection = connection.execute(
                        """
                        UPDATE workflow_failure_injections
                        SET injection_status = 'resumed', resumed_at = now()
                        WHERE run_id = %s
                          AND injection_status = 'triggered'
                        RETURNING node_name, triggered_at, resumed_at
                        """,
                        (run_id,),
                    ).fetchone()
                    if injection is None:
                        raise RuntimeError(
                            "This run has no triggered failure waiting for recovery"
                        )
                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET run_status = 'retry_wait',
                            current_round = 'recovery_resume_requested',
                            next_attempt_at = now(),
                            state_version = state_version + 1,
                            updated_at = now()
                        WHERE run_id = %s
                          AND run_status = 'retry_wait'
                          AND current_round = 'recovery_paused'
                          AND next_attempt_at IS NULL
                          AND graph_version = %s
                          AND lease_owner IS NULL
                          AND latest_checkpoint_id IS NOT NULL
                        RETURNING run_id, latest_checkpoint_id, state_version,
                                  lease_generation
                        """,
                        (run_id, CURRENT_GRAPH_VERSION),
                    ).fetchone()
                    if workflow is None:
                        raise RuntimeError(
                            "Workflow is not durably paused for manual recovery"
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
                        raise RuntimeError("Could not allocate resume audit sequence")
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id, sequence_number, event_type, node_name,
                            actor_type, checkpoint_id, event_data
                        ) VALUES (
                            %s, %s, 'workflow_recovery_requested', %s,
                            'system', %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            run_id,
                            sequence["next_sequence"],
                            injection["node_name"],
                            workflow["latest_checkpoint_id"],
                            Jsonb(
                                {
                                    "retry_node": injection["node_name"],
                                    "prior_lease_generation": workflow[
                                        "lease_generation"
                                    ],
                                    "expected_next_lease_generation": workflow[
                                        "lease_generation"
                                    ]
                                    + 1,
                                    "state_version": workflow["state_version"],
                                }
                            ),
                        ),
                    )
                RECOVERY_RESUMPTIONS.labels(reason="injected_failure").inc()
                return {
                    "run_id": run_id,
                    "node_name": injection["node_name"],
                    "checkpoint_id": workflow["latest_checkpoint_id"],
                    "state_version": workflow["state_version"],
                    "expected_lease_generation": workflow["lease_generation"] + 1,
                }
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")


def record_recovery_worker_claim(
    connection_url: str,
    *,
    lease: WorkflowRun,
    max_attempts: int = 5,
) -> None:
    """Audit the new fenced worker generation that resumes a demo failure."""

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    injection = connection.execute(
                        """
                        SELECT node_name
                        FROM workflow_failure_injections
                        WHERE run_id = %s
                          AND injection_status = 'resumed'
                        """,
                        (lease.run_id,),
                    ).fetchone()
                    if injection is None:
                        return
                    sequence = connection.execute(
                        """
                        SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
                        FROM audit_events
                        WHERE run_id = %s
                        """,
                        (lease.run_id,),
                    ).fetchone()
                    if sequence is None:
                        raise RuntimeError("Could not allocate recovery-claim sequence")
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id, sequence_number, event_type, node_name,
                            actor_type, actor_id, checkpoint_id, event_data
                        ) VALUES (
                            %s, %s, 'workflow_recovery_worker_claimed', %s,
                            'system', %s, %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence["next_sequence"],
                            injection["node_name"],
                            lease.lease_owner,
                            lease.latest_checkpoint_id,
                            Jsonb(
                                {
                                    "lease_generation": lease.lease_generation,
                                    "lease_owner": lease.lease_owner,
                                    "checkpoint_id": lease.latest_checkpoint_id,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                }
                            ),
                        ),
                    )
                return
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")
