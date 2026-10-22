#!/usr/bin/env python3
"""Submit one live ReturnFlow request, verify it, and remove test artifacts."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from langchain_cockroachdb import CockroachDBSaver


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

API_URL = os.environ.get("RETURNFLOW_SMOKE_API_URL", "http://127.0.0.1:8010").rstrip("/")
ORDER_ITEM_ID = UUID("40000000-0000-4000-8000-000000000001")


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        f"{API_URL}{path}",
        data=body,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def main() -> int:
    connection_url = os.environ["CRDB_APP_URL"]
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-RON",
            "order_number": "DEMO-1001",
            "request_text": "I want to return the toaster from order DEMO-1001. It is unused and I have all the packaging.",
        },
    )
    run_id = UUID(created["run_id"])
    return_request_id = UUID(created["return_request_id"])
    snapshot: dict = {}
    try:
        deadline = monotonic() + 45
        while monotonic() < deadline:
            snapshot = request_json(f"/returns/{run_id}")
            if snapshot["run_status"] in ("completed", "rejected", "failed"):
                break
            sleep(0.5)
        if snapshot.get("run_status") != "completed":
            raise RuntimeError(f"API workflow did not complete: {snapshot}")
        expected_nodes = {
            "classify_request",
            "lookup_order",
            "retrieve_policy",
            "assess_fraud",
            "decide_return",
            "reserve_return_items",
            "issue_refund",
        }
        succeeded = {
            attempt["node_name"]
            for attempt in snapshot["node_attempts"]
            if attempt["attempt_status"] == "succeeded"
        }
        if succeeded != expected_nodes:
            raise RuntimeError(f"Unexpected successful node set: {succeeded}")
        if snapshot["refund"]["refund_status"] != "succeeded":
            raise RuntimeError("API snapshot did not contain the successful refund")
        if not snapshot["latest_checkpoint_id"] or not snapshot["trace_id"]:
            raise RuntimeError("API snapshot omitted checkpoint or trace correlation")
        print(
            "PASS: API created, dispatched, checkpointed, audited, and refunded "
            f"run {run_id} with {len(succeeded)} durable node events."
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
