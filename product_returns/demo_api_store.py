"""CockroachDB persistence operations for the interactive ReturnFlow API."""

from __future__ import annotations

import hashlib
import random
from datetime import datetime
from time import sleep
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from product_returns.graph_version import CURRENT_GRAPH_VERSION
from product_returns.failure_injection import ALLOWED_FAILURE_NODES
from product_returns.state import ClassificationResult
from product_returns.workflow_runs import LeaseLostError, WorkflowRun


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def create_submission(
    connection_url: str,
    *,
    customer_external_id: str,
    order_number: str,
    request_text: str,
    failure_node: str | None = None,
    max_attempts: int = 5,
) -> dict[str, Any]:
    """Atomically create the business request and its ready workflow run."""

    customer_external_id = customer_external_id.strip()
    order_number = order_number.strip()
    request_text = request_text.strip()
    if not customer_external_id or not order_number or not request_text:
        raise ValueError("Customer, order number, and request text are required")
    if len(request_text) > 4000:
        raise ValueError("Request text must not exceed 4000 characters")
    if failure_node is not None and failure_node not in ALLOWED_FAILURE_NODES:
        raise ValueError(f"Unsupported failure-injection node {failure_node!r}")

    return_request_id = uuid4()
    run_id = uuid4()
    thread_id = f"returnflow-{run_id}"

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    matched = connection.execute(
                        """
                        SELECT c.customer_id, c.external_customer_id,
                               o.order_id, o.order_number
                        FROM customers AS c
                        JOIN orders AS o ON o.customer_id = c.customer_id
                        WHERE c.external_customer_id = %s
                          AND o.order_number = %s
                        """,
                        (customer_external_id, order_number),
                    ).fetchone()
                    if matched is None:
                        raise LookupError(
                            "The order was not found in the selected customer account"
                        )

                    connection.execute(
                        """
                        INSERT INTO return_requests (
                            return_request_id, customer_id, order_id, request_text
                        ) VALUES (%s, %s, %s, %s)
                        RETURNING NOTHING
                        """,
                        (
                            return_request_id,
                            matched["customer_id"],
                            matched["order_id"],
                            request_text,
                        ),
                    )
                    created = connection.execute(
                        """
                        INSERT INTO workflow_runs (
                            run_id, return_request_id, thread_id, graph_version,
                            current_round, next_nodes
                        ) VALUES (
                            %s, %s, %s, %s, 'classification',
                            ARRAY['classify_request']::STRING[]
                        )
                        RETURNING run_id, return_request_id, thread_id,
                                  run_status, graph_version, created_at
                        """,
                        (
                            run_id,
                            return_request_id,
                            thread_id,
                            CURRENT_GRAPH_VERSION,
                        ),
                    ).fetchone()
                    if created is None:
                        raise RuntimeError("CockroachDB did not return the workflow run")
                    if failure_node is not None:
                        connection.execute(
                            """
                            INSERT INTO workflow_failure_injections (
                                run_id, node_name, failure_mode
                            ) VALUES (%s, %s, %s)
                            RETURNING NOTHING
                            """,
                            (
                                run_id,
                                failure_node,
                                "fail_once_after_provider_success"
                                if failure_node == "issue_refund"
                                else "fail_once_before_node",
                            ),
                        )
                return dict(created)
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")


def list_demo_orders(connection_url: str) -> list[dict[str, Any]]:
    """Return the synthetic order catalog used by presenter controls."""

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT o.order_number, o.currency, o.total_amount, o.ordered_at,
                   c.external_customer_id, c.email,
                   oi.order_item_id, oi.sku, oi.product_name,
                   oi.product_category, oi.quantity, oi.line_total
            FROM orders AS o
            JOIN customers AS c ON c.customer_id = o.customer_id
            JOIN order_items AS oi ON oi.order_id = o.order_id
            WHERE o.order_number LIKE 'DEMO-%'
            ORDER BY o.order_number, oi.order_item_id
            """
        ).fetchall()

    orders: dict[str, dict[str, Any]] = {}
    for row in rows:
        order_number = str(row["order_number"])
        order = orders.setdefault(
            order_number,
            {
                "order_number": order_number,
                "external_customer_id": row["external_customer_id"],
                "customer_name": str(row["email"]).split("@", 1)[0].title(),
                "currency": row["currency"],
                "total_amount": row["total_amount"],
                "ordered_at": row["ordered_at"],
                "items": [],
            },
        )
        order["items"].append(
            {
                "order_item_id": row["order_item_id"],
                "sku": row["sku"],
                "product_name": row["product_name"],
                "product_category": row["product_category"],
                "quantity": row["quantity"],
                "line_total": row["line_total"],
            }
        )
    return list(orders.values())


def list_claimable_run_ids(
    connection_url: str,
    *,
    limit: int = 10,
) -> list[UUID]:
    """Return a small scheduler batch; the later claim remains authoritative."""

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT run_id
            FROM workflow_runs
            WHERE graph_version = %s
              AND (
                  run_status = 'ready'
                  OR (run_status = 'retry_wait' AND next_attempt_at <= now())
                  OR (run_status = 'running' AND lease_expires_at <= now())
              )
            ORDER BY updated_at, run_id
            LIMIT %s
            """,
            (CURRENT_GRAPH_VERSION, limit),
        ).fetchall()
    return [cast(UUID, row["run_id"]) for row in rows]


def load_initial_state(connection_url: str, run_id: UUID) -> dict[str, str]:
    """Load only the immutable customer input needed to start a new graph."""

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        row = connection.execute(
            """
            SELECT wr.thread_id, c.external_customer_id, o.order_number,
                   rr.request_text
            FROM workflow_runs AS wr
            JOIN return_requests AS rr
              ON rr.return_request_id = wr.return_request_id
            JOIN customers AS c ON c.customer_id = rr.customer_id
            JOIN orders AS o ON o.order_id = rr.order_id
            WHERE wr.run_id = %s
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"Workflow run {run_id} was not found")
    return {
        "run_id": str(run_id),
        "thread_id": row["thread_id"],
        "customer_id": row["external_customer_id"],
        "order_number": row["order_number"],
        "customer_message": row["request_text"],
    }


def commit_non_refund_classification(
    connection_url: str,
    *,
    lease: WorkflowRun,
    classification: ClassificationResult,
    checkpoint_id: str,
    max_attempts: int = 5,
) -> None:
    """Explain and finish a request that does not belong in the refund graph."""

    intent = classification["intent"]
    stored_intent = intent if intent in ("complaint", "other") else "other"
    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    workflow = connection.execute(
                        """
                        UPDATE workflow_runs
                        SET run_status = 'rejected', current_round = 'classification',
                            next_nodes = ARRAY[]::STRING[],
                            state_version = state_version + 1,
                            lease_owner = NULL, lease_acquired_at = NULL,
                            last_heartbeat_at = NULL, lease_expires_at = NULL,
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
                        raise LeaseLostError("Classification commit lost its lease fence")
                    connection.execute(
                        """
                        UPDATE return_requests
                        SET classified_intent = %s, request_status = 'rejected',
                            updated_at = now()
                        WHERE return_request_id = %s
                        RETURNING NOTHING
                        """,
                        (stored_intent, workflow["return_request_id"]),
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
                        raise RuntimeError("Could not allocate an audit sequence")
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            run_id, sequence_number, event_type, node_name,
                            actor_type, checkpoint_id, event_data
                        ) VALUES (
                            %s, %s, 'request_routed_out_of_refund',
                            'classify_request', 'system', %s, %s
                        )
                        RETURNING NOTHING
                        """,
                        (
                            lease.run_id,
                            sequence["next_sequence"],
                            checkpoint_id,
                            Jsonb(
                                {
                                    "classification": classification,
                                    "graph_version": CURRENT_GRAPH_VERSION,
                                    "state_version": workflow["state_version"],
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


def load_run_snapshot(
    connection_url: str,
    run_id: UUID,
    *,
    max_attempts: int = 5,
) -> dict[str, Any] | None:
    """Load one consistent run snapshot with full read-transaction retries."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            return _load_run_snapshot_once(connection_url, run_id)
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")


def _load_run_snapshot_once(
    connection_url: str,
    run_id: UUID,
) -> dict[str, Any] | None:
    """Read all related rows in one serializable transaction attempt."""

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        run = connection.execute(
            """
            SELECT wr.run_id, wr.thread_id, wr.run_status, wr.current_round,
                   wr.next_nodes, wr.latest_checkpoint_id, wr.state_version,
                   wr.graph_version, wr.lease_owner, wr.lease_generation,
                   wr.lease_acquired_at, wr.last_heartbeat_at,
                   wr.lease_expires_at, wr.next_attempt_at, wr.created_at,
                   wr.updated_at, rr.return_request_id, rr.request_text,
                   rr.classified_intent, rr.request_status,
                   c.external_customer_id, c.email, o.order_number,
                   o.currency, o.total_amount
            FROM workflow_runs AS wr
            JOIN return_requests AS rr
              ON rr.return_request_id = wr.return_request_id
            JOIN customers AS c ON c.customer_id = rr.customer_id
            JOIN orders AS o ON o.order_id = rr.order_id
            WHERE wr.run_id = %s
            """,
            (run_id,),
        ).fetchone()
        if run is None:
            return None
        attempts = connection.execute(
            """
            SELECT node_attempt_id, node_name, attempt_number, attempt_status,
                   input_state, output_summary, error_code, error_message,
                   started_at, finished_at, duration_ms
            FROM node_attempts
            WHERE run_id = %s
            ORDER BY started_at, node_attempt_id
            """,
            (run_id,),
        ).fetchall()
        approval = connection.execute(
            """
            SELECT approval_request_id, approval_status, refund_amount,
                   currency, approval_reason, requested_at, decided_at,
                   decided_by, decision_note
            FROM approval_requests
            WHERE run_id = %s
            ORDER BY request_number DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        refund = connection.execute(
            """
            SELECT refund_id, refund_status, refund_amount, currency,
                   payment_provider, provider_refund_id, idempotency_key,
                   completed_at
            FROM refunds
            WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
        refund_attempts = connection.execute(
            """
            SELECT ra.attempt_number, ra.attempt_status, ra.provider_request_id,
                   ra.provider_response, ra.error_code, ra.error_message,
                   ra.started_at, ra.finished_at
            FROM refund_attempts AS ra
            JOIN refunds AS r ON r.refund_id = ra.refund_id
            WHERE r.run_id = %s
            ORDER BY ra.attempt_number
            """,
            (run_id,),
        ).fetchall()
        provider_refund = connection.execute(
            """
            SELECT provider_refund_id, idempotency_key, refund_amount,
                   currency, provider_status, request_count,
                   first_requested_at, last_requested_at,
                   count(*) OVER () AS provider_refund_count
            FROM demo_payment_provider_refunds
            WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()
        audit = connection.execute(
            """
            SELECT sequence_number, event_type, node_name, actor_type,
                   actor_id, checkpoint_id, event_data, occurred_at
            FROM audit_events
            WHERE run_id = %s
            ORDER BY sequence_number
            """,
            (run_id,),
        ).fetchall()
        failure_injection = connection.execute(
            """
            SELECT node_name, failure_mode, injection_status,
                   created_at, triggered_at, resumed_at
            FROM workflow_failure_injections
            WHERE run_id = %s
            """,
            (run_id,),
        ).fetchone()

    result = dict(run)
    result["node_attempts"] = [dict(row) for row in attempts]
    result["approval"] = dict(approval) if approval is not None else None
    result["refund"] = dict(refund) if refund is not None else None
    result["refund_attempts"] = [dict(row) for row in refund_attempts]
    result["provider_refund"] = (
        dict(provider_refund) if provider_refund is not None else None
    )
    result["audit_events"] = [dict(row) for row in audit]
    result["failure_injection"] = (
        dict(failure_injection) if failure_injection is not None else None
    )
    result["trace_id"] = hashlib.sha256(
        f"product-returns:{run_id}".encode("utf-8")
    ).hexdigest()[:32]
    return result


def reset_demo_run(
    connection_url: str,
    run_id: UUID,
    *,
    max_attempts: int = 5,
) -> str | None:
    """Remove one synthetic ReturnFlow run and restore its item capacity."""

    for attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    run = connection.execute(
                        """
                        SELECT return_request_id, thread_id, run_status
                        FROM workflow_runs
                        WHERE run_id = %s
                          AND thread_id LIKE 'returnflow-%%'
                        FOR UPDATE
                        """,
                        (run_id,),
                    ).fetchone()
                    if run is None:
                        return None
                    if run["run_status"] == "running":
                        raise RuntimeError("A running demo cannot be reset")
                    request_id = cast(UUID, run["return_request_id"])
                    allocations = connection.execute(
                        """
                        SELECT order_item_id, allocated_quantity, allocation_status
                        FROM return_item_allocations
                        WHERE return_request_id = %s
                        FOR UPDATE
                        """,
                        (request_id,),
                    ).fetchall()
                    for allocation in allocations:
                        reserved = (
                            allocation["allocated_quantity"]
                            if allocation["allocation_status"] == "reserved"
                            else 0
                        )
                        refunded = (
                            allocation["allocated_quantity"]
                            if allocation["allocation_status"] == "refunded"
                            else 0
                        )
                        restored = connection.execute(
                            """
                            UPDATE return_item_capacity
                            SET reserved_quantity = reserved_quantity - %s,
                                refunded_quantity = refunded_quantity - %s,
                                updated_at = now()
                            WHERE order_item_id = %s
                              AND reserved_quantity >= %s
                              AND refunded_quantity >= %s
                            RETURNING order_item_id
                            """,
                            (
                                reserved,
                                refunded,
                                allocation["order_item_id"],
                                reserved,
                                refunded,
                            ),
                        ).fetchone()
                        if restored is None:
                            raise RuntimeError("Demo reset would violate item capacity")

                    connection.execute(
                        "DELETE FROM workflow_failure_injections WHERE run_id = %s RETURNING NOTHING",
                        (run_id,),
                    )
                    connection.execute(
                        "DELETE FROM audit_events WHERE run_id = %s RETURNING NOTHING",
                        (run_id,),
                    )
                    connection.execute(
                        "DELETE FROM node_attempts WHERE run_id = %s RETURNING NOTHING",
                        (run_id,),
                    )
                    connection.execute(
                        """
                        DELETE FROM refund_attempts
                        WHERE refund_id IN (
                            SELECT refund_id FROM refunds WHERE run_id = %s
                        )
                        RETURNING NOTHING
                        """,
                        (run_id,),
                    )
                    connection.execute(
                        "DELETE FROM refunds WHERE run_id = %s RETURNING NOTHING",
                        (run_id,),
                    )
                    connection.execute(
                        """
                        DELETE FROM return_item_allocations
                        WHERE return_request_id = %s
                        RETURNING NOTHING
                        """,
                        (request_id,),
                    )
                    connection.execute(
                        """
                        DELETE FROM return_items
                        WHERE return_request_id = %s
                        RETURNING NOTHING
                        """,
                        (request_id,),
                    )
                    connection.execute(
                        "DELETE FROM approval_requests WHERE run_id = %s RETURNING NOTHING",
                        (run_id,),
                    )
                    connection.execute(
                        """
                        DELETE FROM demo_payment_provider_refunds
                        WHERE run_id = %s
                        RETURNING NOTHING
                        """,
                        (run_id,),
                    )
                    connection.execute(
                        "DELETE FROM workflow_runs WHERE run_id = %s RETURNING NOTHING",
                        (run_id,),
                    )
                    connection.execute(
                        """
                        DELETE FROM return_requests
                        WHERE return_request_id = %s
                        RETURNING NOTHING
                        """,
                        (request_id,),
                    )
                return cast(str, run["thread_id"])
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")
