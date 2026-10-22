#!/usr/bin/env python3
"""Prove that a complaint stops after classification with no refund work."""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen


API_URL = os.environ.get("RETURNFLOW_SMOKE_API_URL", "http://127.0.0.1:8010").rstrip("/")


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
            "request_text": "Should the outside of the toaster get warm? Do I need to be concerned?",
        },
    )
    assert created is not None
    run_id = created["run_id"]
    try:
        deadline = monotonic() + 45
        snapshot: dict = {}
        while monotonic() < deadline:
            result = request_json(f"/returns/{run_id}")
            assert result is not None
            snapshot = result
            if snapshot["run_status"] == "rejected":
                break
            if snapshot["run_status"] in ("completed", "failed"):
                raise RuntimeError(f"Complaint reached an unexpected terminal state: {snapshot}")
            sleep(0.5)
        if snapshot.get("classified_intent") != "complaint":
            raise RuntimeError(f"Complaint intent was not persisted: {snapshot}")
        node_names = [attempt["node_name"] for attempt in snapshot["node_attempts"]]
        if node_names != ["classify_request"]:
            raise RuntimeError(f"Complaint incorrectly entered refund nodes: {node_names}")
        if snapshot["approval"] is not None or snapshot["refund"] is not None:
            raise RuntimeError("Complaint created approval or refund data")
        event_types = [event["event_type"] for event in snapshot["audit_events"]]
        if event_types != ["request_routed_out_of_refund"]:
            raise RuntimeError(f"Complaint audit trail was unexpected: {event_types}")
        print("PASS: complaint stopped after classification with no refund, policy, fraud, or payment work.")
        return 0
    finally:
        request_json(f"/returns/{run_id}", method="DELETE")


if __name__ == "__main__":
    raise SystemExit(main())
