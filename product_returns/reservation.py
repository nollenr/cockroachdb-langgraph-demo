"""Concurrency-safe, item-level return quantity reservations."""

from __future__ import annotations

import random
from collections.abc import Callable
from time import sleep
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from product_returns.state import (
    OrderItemEvidence,
    ReservedReturnItem,
    ReturnReservationResult,
    ReturnWorkflowState,
)


class _QuantityConflict(RuntimeError):
    def __init__(self, item: ReservedReturnItem) -> None:
        super().__init__("Requested return quantity is no longer available")
        self.item = item


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def _requested_items(state: ReturnWorkflowState) -> list[OrderItemEvidence]:
    order = state.get("order_lookup")
    if order is None or not order["found"] or not order["customer_match"]:
        raise ValueError("Quantity reservation requires a matched order")
    if not order["items"]:
        raise ValueError("Quantity reservation requires at least one order item")
    return sorted(order["items"], key=lambda item: item["order_item_id"])


def reserve_return_quantities(
    connection_url: str,
    state: ReturnWorkflowState,
    *,
    max_attempts: int = 5,
) -> ReturnReservationResult:
    """Reserve every requested line atomically or return a business conflict."""

    run_id = UUID(state["run_id"])
    requested_items = _requested_items(state)
    for attempt in range(max_attempts):
        try:
            try:
                with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                    with connection.transaction():
                        request = connection.execute(
                            """
                            SELECT wr.return_request_id, rr.order_id
                            FROM workflow_runs AS wr
                            JOIN return_requests AS rr
                              ON rr.return_request_id = wr.return_request_id
                            WHERE wr.run_id = %s
                              AND wr.run_status = 'running'
                            FOR UPDATE OF rr
                            """,
                            (run_id,),
                        ).fetchone()
                        if request is None or request["order_id"] is None:
                            raise RuntimeError("Active workflow has no returnable order")
                        return_request_id = cast(UUID, request["return_request_id"])
                        order_id = cast(UUID, request["order_id"])
                        reserved_items: list[ReservedReturnItem] = []

                        for item in requested_items:
                            order_item_id = UUID(item["order_item_id"])
                            requested_quantity = int(item["quantity"])
                            existing = connection.execute(
                                """
                                SELECT allocated_quantity, allocation_status
                                FROM return_item_allocations
                                WHERE return_request_id = %s
                                  AND order_item_id = %s
                                """,
                                (return_request_id, order_item_id),
                            ).fetchone()
                            if existing is not None:
                                if (
                                    int(existing["allocated_quantity"])
                                    != requested_quantity
                                    or existing["allocation_status"]
                                    not in ("reserved", "refunded")
                                ):
                                    raise RuntimeError(
                                        "Existing allocation does not match this request"
                                    )
                                capacity = connection.execute(
                                    """
                                    SELECT purchased_quantity, reserved_quantity,
                                           refunded_quantity
                                    FROM return_item_capacity
                                    WHERE order_item_id = %s
                                    """,
                                    (order_item_id,),
                                ).fetchone()
                                if capacity is None:
                                    raise RuntimeError("Existing allocation has no capacity row")
                                reserved_items.append(
                                    {
                                        "order_item_id": item["order_item_id"],
                                        "sku": item["sku"],
                                        "purchased_quantity": int(
                                            capacity["purchased_quantity"]
                                        ),
                                        "requested_quantity": requested_quantity,
                                        "available_before": requested_quantity,
                                    }
                                )
                                continue

                            connection.execute(
                                """
                                INSERT INTO return_item_capacity (
                                    order_item_id, purchased_quantity
                                )
                                SELECT order_item_id, quantity
                                FROM order_items
                                WHERE order_item_id = %s
                                  AND order_id = %s
                                ON CONFLICT (order_item_id) DO NOTHING
                                RETURNING NOTHING
                                """,
                                (order_item_id, order_id),
                            )
                            capacity = connection.execute(
                                """
                                UPDATE return_item_capacity
                                SET
                                    reserved_quantity = reserved_quantity + %s,
                                    updated_at = now()
                                WHERE order_item_id = %s
                                  AND purchased_quantity
                                      - reserved_quantity
                                      - refunded_quantity >= %s
                                RETURNING
                                    purchased_quantity,
                                    reserved_quantity - %s AS reserved_before,
                                    refunded_quantity
                                """,
                                (
                                    requested_quantity,
                                    order_item_id,
                                    requested_quantity,
                                    requested_quantity,
                                ),
                            ).fetchone()
                            if capacity is None:
                                current = connection.execute(
                                    """
                                    SELECT purchased_quantity, reserved_quantity,
                                           refunded_quantity
                                    FROM return_item_capacity
                                    WHERE order_item_id = %s
                                    """,
                                    (order_item_id,),
                                ).fetchone()
                                if current is None:
                                    raise RuntimeError(
                                        "Requested item does not belong to the return order"
                                    )
                                raise _QuantityConflict(
                                    {
                                        "order_item_id": item["order_item_id"],
                                        "sku": item["sku"],
                                        "purchased_quantity": int(
                                            current["purchased_quantity"]
                                        ),
                                        "requested_quantity": requested_quantity,
                                        "available_before": int(
                                            current["purchased_quantity"]
                                            - current["reserved_quantity"]
                                            - current["refunded_quantity"]
                                        ),
                                    }
                                )

                            available_before = int(
                                capacity["purchased_quantity"]
                                - capacity["reserved_before"]
                                - capacity["refunded_quantity"]
                            )
                            connection.execute(
                                """
                                INSERT INTO return_items (
                                    return_request_id, order_item_id,
                                    requested_quantity, return_reason,
                                    requested_refund_amount
                                ) VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (return_request_id, order_item_id)
                                DO NOTHING
                                RETURNING NOTHING
                                """,
                                (
                                    return_request_id,
                                    order_item_id,
                                    requested_quantity,
                                    "Requested through the returns workflow.",
                                    item["line_total"],
                                ),
                            )
                            connection.execute(
                                """
                                INSERT INTO return_item_allocations (
                                    return_request_id, order_item_id,
                                    allocated_quantity, allocation_status
                                ) VALUES (%s, %s, %s, 'reserved')
                                RETURNING NOTHING
                                """,
                                (return_request_id, order_item_id, requested_quantity),
                            )
                            reserved_items.append(
                                {
                                    "order_item_id": item["order_item_id"],
                                    "sku": item["sku"],
                                    "purchased_quantity": int(
                                        capacity["purchased_quantity"]
                                    ),
                                    "requested_quantity": requested_quantity,
                                    "available_before": available_before,
                                }
                            )

                    return {
                        "status": "reserved",
                        "reason_code": "RETURN_QUANTITY_RESERVED",
                        "explanation": (
                            "The requested item quantities are reserved for this return."
                        ),
                        "items": reserved_items,
                    }
            except _QuantityConflict as conflict:
                return {
                    "status": "conflict",
                    "reason_code": "RETURN_QUANTITY_UNAVAILABLE",
                    "explanation": (
                        "At least one requested quantity is already reserved or refunded."
                    ),
                    "items": [conflict.item],
                }
        except psycopg.errors.SerializationFailure:
            if attempt + 1 >= max_attempts:
                raise
            _retry_delay(attempt)
    raise AssertionError("Unreachable transaction retry state")


def _allocation_rows(
    connection: psycopg.Connection[dict[str, Any]],
    return_request_id: UUID,
) -> list[dict[str, Any]]:
    return connection.execute(
        """
        SELECT order_item_id, allocated_quantity
        FROM return_item_allocations
        WHERE return_request_id = %s
          AND allocation_status = 'reserved'
        ORDER BY order_item_id
        FOR UPDATE
        """,
        (return_request_id,),
    ).fetchall()


def release_return_reservations(
    connection: psycopg.Connection[dict[str, Any]],
    return_request_id: UUID,
) -> int:
    """Release this request's quantities inside its terminal transaction."""

    rows = _allocation_rows(connection, return_request_id)
    for row in rows:
        updated = connection.execute(
            """
            UPDATE return_item_capacity
            SET
                reserved_quantity = reserved_quantity - %s,
                updated_at = now()
            WHERE order_item_id = %s
              AND reserved_quantity >= %s
            RETURNING order_item_id
            """,
            (row["allocated_quantity"], row["order_item_id"], row["allocated_quantity"]),
        ).fetchone()
        if updated is None:
            raise RuntimeError("Return capacity could not release reserved quantity")
    connection.execute(
        """
        UPDATE return_item_allocations
        SET allocation_status = 'released', updated_at = now()
        WHERE return_request_id = %s
          AND allocation_status = 'reserved'
        RETURNING NOTHING
        """,
        (return_request_id,),
    )
    return len(rows)


def finalize_return_reservations(
    connection: psycopg.Connection[dict[str, Any]],
    return_request_id: UUID,
) -> int:
    """Convert reserved quantities to refunded inside refund completion."""

    rows = _allocation_rows(connection, return_request_id)
    for row in rows:
        updated = connection.execute(
            """
            UPDATE return_item_capacity
            SET
                reserved_quantity = reserved_quantity - %s,
                refunded_quantity = refunded_quantity + %s,
                updated_at = now()
            WHERE order_item_id = %s
              AND reserved_quantity >= %s
              AND refunded_quantity + %s <= purchased_quantity
            RETURNING order_item_id
            """,
            (
                row["allocated_quantity"],
                row["allocated_quantity"],
                row["order_item_id"],
                row["allocated_quantity"],
                row["allocated_quantity"],
            ),
        ).fetchone()
        if updated is None:
            raise RuntimeError("Return capacity could not finalize refunded quantity")
    connection.execute(
        """
        UPDATE return_item_allocations
        SET allocation_status = 'refunded', updated_at = now()
        WHERE return_request_id = %s
          AND allocation_status = 'reserved'
        RETURNING NOTHING
        """,
        (return_request_id,),
    )
    return len(rows)


def create_reserve_return_items_node(
    connection_url: str,
) -> Callable[[ReturnWorkflowState], dict[str, ReturnReservationResult]]:
    """Build the graph node that atomically reserves all requested quantities."""

    def reserve_return_items(
        state: ReturnWorkflowState,
    ) -> dict[str, ReturnReservationResult]:
        return {"return_reservation": reserve_return_quantities(connection_url, state)}

    return reserve_return_items


def retryable_reservation_error(error: Exception) -> bool:
    return isinstance(error, psycopg.OperationalError)
