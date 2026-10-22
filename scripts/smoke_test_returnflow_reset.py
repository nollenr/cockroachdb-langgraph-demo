#!/usr/bin/env python3
"""Prove that replay reset restores a completed synthetic demo safely."""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

import psycopg
from langchain_cockroachdb import CockroachDBSaver
from psycopg.rows import dict_row


API_URL = os.environ.get("RETURNFLOW_SMOKE_API_URL", "http://127.0.0.1:8010").rstrip("/")
ORDER_ITEM_ID = UUID("40000000-0000-4000-8000-000000000001")


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict | None:
    request = Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        if response.status == 204:
            return None
        return json.load(response)


def main() -> int:
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-RON",
            "order_number": "DEMO-1001",
            "request_text": "I want to return the toaster from order DEMO-1001. It is unused and I have all the packaging.",
        },
    )
    assert created is not None
    run_id = UUID(created["run_id"])
    thread_id = created["thread_id"]
    deadline = monotonic() + 45
    snapshot: dict = {}
    while monotonic() < deadline:
        result = request_json(f"/returns/{run_id}")
        assert result is not None
        snapshot = result
        if snapshot["run_status"] == "completed":
            break
        if snapshot["run_status"] in ("rejected", "failed"):
            raise RuntimeError(f"Reset test workflow failed: {snapshot}")
        sleep(0.5)
    if snapshot.get("run_status") != "completed":
        raise RuntimeError("Reset test workflow did not complete")

    request_json(f"/returns/{run_id}", method="DELETE")
    try:
        request_json(f"/returns/{run_id}")
    except HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise RuntimeError("Reset run remained visible through the API")

    with psycopg.connect(os.environ["CRDB_APP_URL"], row_factory=dict_row) as connection:
        capacity = connection.execute(
            """
            SELECT reserved_quantity, refunded_quantity
            FROM return_item_capacity
            WHERE order_item_id = %s
            """,
            (ORDER_ITEM_ID,),
        ).fetchone()
        provider_count = connection.execute(
            "SELECT count(*) AS row_count FROM demo_payment_provider_refunds WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    if capacity is None or capacity["reserved_quantity"] != 0 or capacity["refunded_quantity"] != 0:
        raise RuntimeError(f"Reset did not restore item capacity: {capacity}")
    if provider_count is None or provider_count["row_count"] != 0:
        raise RuntimeError("Reset left a provider-ledger row")
    with CockroachDBSaver.from_conn_string(os.environ["CRDB_APP_URL"]) as saver:
        checkpoint = saver.get_tuple({"configurable": {"thread_id": thread_id}})
    if checkpoint is not None:
        raise RuntimeError("Reset left a LangGraph checkpoint")
    print("PASS: synthetic reset removed the run and restored refund capacity for replay.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
