#!/usr/bin/env python3
"""Verify grounded safety insight, unchanged routing, and customer acknowledgement."""

from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from langchain_cockroachdb import CockroachDBSaver


API_URL = os.environ.get("RETURNFLOW_SMOKE_API_URL", "http://127.0.0.1:8010").rstrip("/")
ORDER_ITEM_ID = UUID("40000000-0000-4000-8000-000000000001")
MESSAGE = (
    "I want to return the toaster from order DEMO-1001. I've used it quite a bit "
    "but it gets really hot and I'm worried it will scorch my countertops."
)


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{API_URL}{path}",
        data=body,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def node_output(snapshot: dict, node_name: str, field: str) -> dict:
    attempts = [
        item for item in snapshot["node_attempts"]
        if item["node_name"] == node_name and item["attempt_status"] == "succeeded"
    ]
    if not attempts:
        raise RuntimeError(f"Missing successful {node_name} attempt")
    return attempts[-1]["output_summary"][field]


def main() -> int:
    connection_url = os.environ["CRDB_APP_URL"]
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-RON",
            "order_number": "DEMO-1001",
            "request_text": MESSAGE,
        },
    )
    run_id = UUID(created["run_id"])
    return_request_id = UUID(created["return_request_id"])
    snapshot: dict = {}
    try:
        deadline = monotonic() + 60
        while monotonic() < deadline:
            snapshot = request_json(f"/returns/{run_id}")
            if snapshot["run_status"] in ("completed", "rejected", "failed"):
                break
            sleep(0.5)
        if snapshot.get("run_status") != "completed":
            raise RuntimeError(f"Safety workflow did not complete: {snapshot}")

        classification = node_output(snapshot, "classify_request", "classification")
        concern = classification["product_safety_concern"]
        if (
            concern["status"] != "present"
            or concern["category"] not in ("overheating", "property_damage")
        ):
            raise RuntimeError(f"Unexpected safety extraction: {concern}")
        if (
            not concern["verified_in_message"]
            or concern["supporting_text"].casefold() not in MESSAGE.casefold()
        ):
            raise RuntimeError(f"Safety extraction was not grounded: {concern}")

        decision = node_output(snapshot, "decide_return", "decision")
        if decision["outcome"] != "approved_for_refund":
            raise RuntimeError("Safety insight changed the eligible return outcome")
        if decision["reason_codes"] != ["ELIGIBLE_STANDARD_RETURN"]:
            raise RuntimeError("Safety insight changed deterministic routing")
        insights = decision["customer_insights"]
        if len(insights) != 1 or insights[0]["code"] != "POTENTIAL_PRODUCT_SAFETY_CONCERN":
            raise RuntimeError(f"Expected one safety insight, got {insights}")
        if "product-safety follow-up" not in (decision["customer_acknowledgement"] or ""):
            raise RuntimeError("Customer acknowledgement was not recorded")

        print(
            "PASS: AI grounded the overheating concern, the deterministic rules "
            "still approved the refund, and the acknowledgement was checkpointed."
        )
        return 0
    finally:
        thread_id = snapshot.get("thread_id", created.get("thread_id"))
        if thread_id:
            with CockroachDBSaver.from_conn_string(connection_url) as saver:
                saver.delete_thread(thread_id)
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute("DELETE FROM audit_events WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM node_attempts WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM refund_attempts WHERE refund_id IN (SELECT refund_id FROM refunds WHERE run_id = %s)",
                (run_id,),
            )
            connection.execute("DELETE FROM refunds WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_item_allocations WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "DELETE FROM return_items WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "UPDATE return_item_capacity SET reserved_quantity = 0, refunded_quantity = 0, updated_at = now() WHERE order_item_id = %s",
                (ORDER_ITEM_ID,),
            )
            connection.execute("DELETE FROM approval_requests WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = %s",
                (return_request_id,),
            )
            connection.execute(
                "DELETE FROM demo_payment_provider_refunds WHERE run_id = %s",
                (run_id,),
            )


if __name__ == "__main__":
    raise SystemExit(main())
