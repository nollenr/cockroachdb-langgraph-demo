#!/usr/bin/env python3
"""Prove the live ReturnFlow API's verified-policy denial path."""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from langchain_cockroachdb import CockroachDBSaver


API_URL = os.environ.get("RETURNFLOW_SMOKE_API_URL", "http://127.0.0.1:8010").rstrip("/")


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    request = Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
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
            "customer_external_id": "CUST-BOB",
            "order_number": "DEMO-1003",
            "request_text": "I want a refund for the gift card on order DEMO-1003.",
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
        if snapshot.get("run_status") != "rejected":
            raise RuntimeError(f"Gift-card workflow did not reject: {snapshot}")
        if snapshot["refund"] is not None:
            raise RuntimeError("Gift-card denial unexpectedly created a refund")
        decision = next(
            attempt for attempt in snapshot["node_attempts"]
            if attempt["node_name"] == "decide_return"
            and attempt["attempt_status"] == "succeeded"
        )["output_summary"]["decision"]
        if decision["reason_codes"] != ["GIFT_CARD_FINAL_SALE"]:
            raise RuntimeError(f"Unexpected denial reasons: {decision['reason_codes']}")
        policy = next(
            attempt for attempt in snapshot["node_attempts"]
            if attempt["node_name"] == "retrieve_policy"
            and attempt["attempt_status"] == "succeeded"
        )["output_summary"]["policy_evidence"]
        clause_keys = {citation["clause_key"] for citation in policy["citations"]}
        if not policy["verified"] or "RET-EXCEPTION-001" not in clause_keys:
            raise RuntimeError("Gift-card denial did not carry verified policy evidence")
        print(
            "PASS: API rejected the gift card with GIFT_CARD_FINAL_SALE, "
            "verified RET-EXCEPTION-001, and created no refund."
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
            connection.execute("DELETE FROM approval_requests WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = %s",
                (return_request_id,),
            )


if __name__ == "__main__":
    raise SystemExit(main())
