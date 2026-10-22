#!/usr/bin/env python3
"""Prove selective replay, manual recovery, and run-specific SQL inspection."""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from langchain_cockroachdb import CockroachDBSaver
from psycopg.rows import dict_row


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
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def wait_for(run_id: UUID, expected_status: str, timeout_seconds: float = 60) -> dict:
    deadline = monotonic() + timeout_seconds
    snapshot: dict = {}
    while monotonic() < deadline:
        snapshot = request_json(f"/returns/{run_id}")
        if snapshot["run_status"] == expected_status:
            return snapshot
        if snapshot["run_status"] in ("completed", "rejected", "failed"):
            break
        sleep(0.5)
    raise RuntimeError(f"Run did not reach {expected_status!r}: {snapshot}")


def attempts_by_node(snapshot: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for attempt in snapshot["node_attempts"]:
        result.setdefault(attempt["node_name"], []).append(attempt)
    return result


def main() -> int:
    connection_url = os.environ["CRDB_APP_URL"]
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-RON",
            "order_number": "DEMO-1001",
            "request_text": "I want to return the toaster from order DEMO-1001.",
            "failure_node": "assess_fraud",
        },
    )
    run_id = UUID(created["run_id"])
    return_request_id = UUID(created["return_request_id"])
    snapshot: dict = {}
    try:
        paused = wait_for(run_id, "retry_wait")
        injection = paused["failure_injection"]
        if injection["injection_status"] != "triggered":
            raise RuntimeError(f"Failure was not durably triggered: {injection}")
        if paused["lease_owner"] is not None or paused["next_attempt_at"] is not None:
            raise RuntimeError("Paused run retained a worker lease or automatic retry time")
        if paused["lease_generation"] != 1:
            raise RuntimeError(f"Expected generation 1 pause: {paused['lease_generation']}")

        attempts = attempts_by_node(paused)
        for node_name in ("lookup_order", "retrieve_policy"):
            node_attempts = attempts.get(node_name, [])
            if len(node_attempts) != 1 or node_attempts[0]["attempt_status"] != "succeeded":
                raise RuntimeError(f"Sibling {node_name} was not preserved: {node_attempts}")
        fraud_attempts = attempts.get("assess_fraud", [])
        if len(fraud_attempts) != 1 or fraud_attempts[0]["attempt_status"] != "retryable_failure":
            raise RuntimeError(f"Expected one retryable fraud failure: {fraud_attempts}")

        inspection = request_json(f"/returns/{run_id}/inspection-sql")
        sql = inspection["sql"]
        if str(run_id) not in sql or "__RUN_ID__" in sql:
            raise RuntimeError("Inspection SQL was not scoped to the exact run UUID")
        if "checkpoint_writes" not in sql or "workflow_failure_injections" not in sql:
            raise RuntimeError("Inspection SQL omitted resilience evidence")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            writes = connection.execute(
                """
                SELECT count(*) AS write_count
                FROM checkpoint_writes AS cw
                JOIN workflow_runs AS wr ON wr.thread_id = cw.thread_id
                WHERE wr.run_id = %s
                """,
                (run_id,),
            ).fetchone()
        if writes is None or int(writes["write_count"]) == 0:
            raise RuntimeError("LangGraph stored no pending/checkpoint writes")

        request_json(f"/returns/{run_id}/resume", method="POST", payload={})
        snapshot = wait_for(run_id, "completed")
        attempts = attempts_by_node(snapshot)
        if len(attempts.get("lookup_order", [])) != 1:
            raise RuntimeError("Order lookup reran instead of reusing its saved result")
        if len(attempts.get("retrieve_policy", [])) != 1:
            raise RuntimeError("Policy retrieval reran instead of reusing its saved result")
        fraud_attempts = attempts.get("assess_fraud", [])
        if [item["attempt_status"] for item in fraud_attempts] != [
            "retryable_failure",
            "succeeded",
        ]:
            raise RuntimeError(f"Fraud retry history was incorrect: {fraud_attempts}")
        if snapshot["lease_generation"] != 2:
            raise RuntimeError("A new worker generation did not claim the resumed run")
        event_types = [event["event_type"] for event in snapshot["audit_events"]]
        required_events = {
            "injected_failure_paused",
            "workflow_recovery_requested",
            "workflow_recovery_worker_claimed",
        }
        if not required_events.issubset(event_types):
            raise RuntimeError(f"Recovery audit events were incomplete: {event_types}")

        print(
            "PASS: assess_fraud failed once, order and policy stayed at one "
            "attempt, the lease was released, run-specific SQL was generated, "
            "and generation 2 resumed to one completed refund."
        )
        return 0
    finally:
        thread_id = snapshot.get("thread_id", created.get("thread_id"))
        if thread_id:
            with CockroachDBSaver.from_conn_string(connection_url) as saver:
                saver.delete_thread(thread_id)
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute("DELETE FROM workflow_failure_injections WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM audit_events WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM node_attempts WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM refund_attempts WHERE refund_id IN (SELECT refund_id FROM refunds WHERE run_id = %s)",
                (run_id,),
            )
            connection.execute("DELETE FROM refunds WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM return_item_allocations WHERE return_request_id = %s", (return_request_id,))
            connection.execute("DELETE FROM return_items WHERE return_request_id = %s", (return_request_id,))
            connection.execute(
                "UPDATE return_item_capacity SET reserved_quantity = 0, refunded_quantity = 0, updated_at = now() WHERE order_item_id = %s",
                (ORDER_ITEM_ID,),
            )
            connection.execute("DELETE FROM approval_requests WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute("DELETE FROM return_requests WHERE return_request_id = %s", (return_request_id,))
            connection.execute("DELETE FROM demo_payment_provider_refunds WHERE run_id = %s", (run_id,))


if __name__ == "__main__":
    raise SystemExit(main())
