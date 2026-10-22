#!/usr/bin/env python3
"""Prove concurrent item reservations, release, and permanent refund usage."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import cast
from urllib.parse import urlparse
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.reservation import (  # noqa: E402
    finalize_return_reservations,
    release_return_reservations,
    reserve_return_quantities,
)
from product_returns.reservation_store import commit_reservation_conflict  # noqa: E402
from product_returns.state import ReturnWorkflowState  # noqa: E402
from product_returns.workflow_runs import (  # noqa: E402
    WorkflowRun,
    claim_workflow_run,
    create_workflow_run,
    publish_checkpoint,
)


def validated_app_url() -> str:
    url = os.environ.get("CRDB_APP_URL")
    if not url:
        raise RuntimeError("CRDB_APP_URL is not set")
    parsed = urlparse(url)
    if parsed.username != "product_returns_app" or parsed.path != "/product_returns":
        raise RuntimeError("CRDB_APP_URL must use the product_returns application role")
    return url


def state_for(run_id: UUID, thread_id: str, order_id: UUID, order_item_id: UUID) -> ReturnWorkflowState:
    return {
        "run_id": str(run_id),
        "thread_id": thread_id,
        "customer_id": "CUST-CONCURRENCY",
        "order_number": "RESERVATION-SMOKE",
        "customer_message": "Return both units.",
        "order_lookup": {
            "found": True,
            "customer_match": True,
            "order_number": "RESERVATION-SMOKE",
            "order_id": str(order_id),
            "order_status": "delivered",
            "currency": "USD",
            "ordered_at": None,
            "days_since_order": 1,
            "refundable_item_total": "21.60",
            "shipping_amount": "0.00",
            "items": [
                {
                    "order_item_id": str(order_item_id),
                    "sku": "RESERVE-SMOKE",
                    "product_name": "Reservation Smoke Product",
                    "product_category": "test",
                    "quantity": 2,
                    "unit_price": "10.00",
                    "tax_amount": "1.60",
                    "line_total": "21.60",
                    "activated_at": None,
                }
            ],
        },
    }


def main() -> int:
    connection_url = validated_app_url()
    customer_id = uuid4()
    product_id = uuid4()
    order_id = uuid4()
    order_item_id = uuid4()
    request_ids = [uuid4(), uuid4(), uuid4()]
    run_ids = [uuid4(), uuid4(), uuid4()]
    thread_ids = [f"reservation-smoke-{uuid4()}" for _ in range(3)]

    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO customers (customer_id, external_customer_id, email)
            VALUES (%s, %s, %s)
            """,
            (customer_id, f"RESERVE-{customer_id}", f"{customer_id}@example.test"),
        )
        connection.execute(
            """
            INSERT INTO products (product_id, sku, product_name, product_category)
            VALUES (%s, %s, 'Reservation Smoke Product', 'test')
            """,
            (product_id, f"RESERVE-{product_id}"),
        )
        connection.execute(
            """
            INSERT INTO orders (
                order_id, order_number, customer_id, order_status, currency,
                subtotal_amount, tax_amount, shipping_amount, total_amount,
                ordered_at
            ) VALUES (%s, 'RESERVATION-SMOKE', %s, 'delivered', 'USD',
                      20.00, 1.60, 0.00, 21.60, now() - INTERVAL '1 day')
            """,
            (order_id, customer_id),
        )
        connection.execute(
            """
            INSERT INTO order_items (
                order_item_id, order_id, product_id, sku, product_name,
                product_category, quantity, unit_price, tax_amount, line_total
            ) VALUES (%s, %s, %s, 'RESERVE-SMOKE',
                      'Reservation Smoke Product', 'test', 2, 10.00, 1.60, 21.60)
            """,
            (order_item_id, order_id, product_id),
        )
        for request_id in request_ids:
            connection.execute(
                """
                INSERT INTO return_requests (
                    return_request_id, customer_id, order_id, request_text
                ) VALUES (%s, %s, %s, 'Return both units.')
                """,
                (request_id, customer_id, order_id),
            )

    try:
        states: list[ReturnWorkflowState] = []
        leases: list[WorkflowRun] = []
        for index in range(3):
            create_workflow_run(
                connection_url,
                return_request_id=request_ids[index],
                thread_id=thread_ids[index],
                run_id=run_ids[index],
            )
            lease = claim_workflow_run(
                connection_url,
                run_id=run_ids[index],
                worker_id=f"reservation-worker-{index}",
                lease_seconds=60,
            )
            if lease is None:
                raise RuntimeError("Could not claim reservation smoke workflow")
            leases.append(lease)
            states.append(state_for(run_ids[index], thread_ids[index], order_id, order_item_id))

        barrier = Barrier(2)

        def compete(state: ReturnWorkflowState):
            barrier.wait()
            return reserve_return_quantities(connection_url, state)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(compete, states[index]) for index in range(2)]
            first_results = [future.result() for future in futures]

        statuses = sorted(result["status"] for result in first_results)
        if statuses != ["conflict", "reserved"]:
            raise RuntimeError(f"Concurrent results were not one winner/one conflict: {statuses}")
        winner_index = next(
            index for index, result in enumerate(first_results) if result["status"] == "reserved"
        )
        loser_index = 1 - winner_index
        print("PASS: simultaneous requests produced one reservation and one conflict.")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            with connection.transaction():
                released = release_return_reservations(connection, request_ids[winner_index])
        if released != 1:
            raise RuntimeError("Rejected-request simulation did not release one allocation")
        second_result = reserve_return_quantities(connection_url, states[loser_index])
        if second_result["status"] != "reserved":
            raise RuntimeError("Released quantity was not reusable by another request")
        print("PASS: releasing a denied request made its quantity available again.")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            with connection.transaction():
                finalized = finalize_return_reservations(connection, request_ids[loser_index])
        if finalized != 1:
            raise RuntimeError("Refund simulation did not finalize one allocation")
        third_result = reserve_return_quantities(connection_url, states[2])
        if third_result["status"] != "conflict":
            raise RuntimeError("Refunded quantity was incorrectly available again")

        published = publish_checkpoint(
            connection_url,
            run_id=run_ids[2],
            worker_id=cast(str, leases[2].lease_owner),
            lease_generation=leases[2].lease_generation,
            expected_state_version=leases[2].state_version,
            checkpoint_id="reservation-conflict-smoke-checkpoint",
            current_round="reservation",
            next_nodes=(),
        )
        if published is None:
            raise RuntimeError("Could not publish the reservation-conflict checkpoint")
        conflict_commit = commit_reservation_conflict(
            connection_url,
            lease=published,
            reservation=third_result,
            checkpoint_id="reservation-conflict-smoke-checkpoint",
        )
        if conflict_commit.run_status != "rejected":
            raise RuntimeError("Quantity conflict was not committed as a rejection")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            capacity = connection.execute(
                """
                SELECT purchased_quantity, reserved_quantity, refunded_quantity
                FROM return_item_capacity
                WHERE order_item_id = %s
                """,
                (order_item_id,),
            ).fetchone()
        if capacity is None or (
            capacity["purchased_quantity"],
            capacity["reserved_quantity"],
            capacity["refunded_quantity"],
        ) != (2, 0, 2):
            raise RuntimeError(f"Unexpected final capacity: {capacity}")
        print("PASS: refunded quantity is permanently consumed and cannot be returned twice.")
        print("PASS: the conflict became an explained, audited workflow rejection.")
        return 0
    finally:
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute("DELETE FROM audit_events WHERE run_id = ANY(%s)", (run_ids,))
            connection.execute(
                "DELETE FROM return_item_allocations WHERE return_request_id = ANY(%s)",
                (request_ids,),
            )
            connection.execute(
                "DELETE FROM return_items WHERE return_request_id = ANY(%s)",
                (request_ids,),
            )
            connection.execute("DELETE FROM workflow_runs WHERE run_id = ANY(%s)", (run_ids,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = ANY(%s)",
                (request_ids,),
            )
            connection.execute(
                "DELETE FROM return_item_capacity WHERE order_item_id = %s",
                (order_item_id,),
            )
            connection.execute("DELETE FROM order_items WHERE order_item_id = %s", (order_item_id,))
            connection.execute("DELETE FROM orders WHERE order_id = %s", (order_id,))
            connection.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
            connection.execute("DELETE FROM customers WHERE customer_id = %s", (customer_id,))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Return quantity reservation smoke test failed: {error}", file=sys.stderr)
        raise
