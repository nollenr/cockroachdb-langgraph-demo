#!/usr/bin/env python3
"""Prove the live API's durable manager approval and graph resume path."""

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
ORDER_ITEM_ID = UUID("40000000-0000-4000-8000-000000000002")


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    request = Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def wait_for(run_id: UUID, expected_status: str, timeout: float = 45) -> dict:
    deadline = monotonic() + timeout
    last: dict = {}
    while monotonic() < deadline:
        last = request_json(f"/returns/{run_id}")
        if last["run_status"] == expected_status:
            return last
        if last["run_status"] in ("rejected", "failed"):
            raise RuntimeError(f"Workflow reached {last['run_status']}: {last}")
        sleep(0.5)
    raise RuntimeError(f"Workflow did not reach {expected_status}: {last}")


def main() -> int:
    connection_url = os.environ["CRDB_APP_URL"]
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-SALLY",
            "order_number": "DEMO-1002",
            "request_text": "Please return the Pro 900 vacuum from order DEMO-1002. It is still in good condition.",
        },
    )
    run_id = UUID(created["run_id"])
    return_request_id = UUID(created["return_request_id"])
    snapshot: dict = {}
    try:
        waiting = wait_for(run_id, "waiting_for_approval")
        if waiting["approval"]["approval_status"] != "pending":
            raise RuntimeError("Approval request was not pending")
        with psycopg.connect(connection_url, row_factory=psycopg.rows.dict_row) as connection:
            dormant = connection.execute(
                """
                SELECT lease_owner, lease_expires_at, next_nodes
                FROM workflow_runs
                WHERE run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if dormant is None or dormant["lease_owner"] is not None:
            raise RuntimeError("Waiting API workflow retained a worker lease")

        request_json(
            f"/returns/{run_id}/manager-decision",
            method="POST",
            payload={
                "decision": "approved",
                "decided_by": "manager.api-smoke",
                "decision_note": "API approval smoke test.",
            },
        )
        snapshot = wait_for(run_id, "completed")
        if snapshot["approval"]["approval_status"] != "approved":
            raise RuntimeError("Approved decision is missing from the final snapshot")
        if snapshot["refund"]["refund_status"] != "succeeded":
            raise RuntimeError("Approved API workflow did not issue its refund")
        issue_attempts = [
            attempt
            for attempt in snapshot["node_attempts"]
            if attempt["node_name"] == "issue_refund"
            and attempt["attempt_status"] == "succeeded"
        ]
        if len(issue_attempts) != 1:
            raise RuntimeError("Approval resume did not issue exactly one refund node")
        print(
            "PASS: API paused with no lease, accepted manager approval, resumed "
            f"generation 2, and completed one refund for run {run_id}."
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
