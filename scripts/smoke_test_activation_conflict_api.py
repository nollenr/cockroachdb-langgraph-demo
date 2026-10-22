#!/usr/bin/env python3
"""Prove AI claim extraction plus deterministic activation-conflict review."""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen


API_URL = os.environ.get("RETURNFLOW_SMOKE_API_URL", "http://127.0.0.1:8010").rstrip("/")
CUSTOMER_MESSAGE = (
    "I want to return the iPhone from order DEMO-1004. "
    "The phone has not been activated and I would like to return it."
)


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


def wait_for(run_id: str, expected_status: str, timeout: float = 45) -> dict:
    deadline = monotonic() + timeout
    last: dict = {}
    while monotonic() < deadline:
        result = request_json(f"/returns/{run_id}")
        assert result is not None
        last = result
        if last["run_status"] == expected_status:
            return last
        if last["run_status"] in ("rejected", "failed"):
            raise RuntimeError(
                f"Activation-conflict workflow reached {last['run_status']}: {last}"
            )
        sleep(0.5)
    raise RuntimeError(f"Workflow did not reach {expected_status}: {last}")


def node_output(snapshot: dict, node_name: str, field: str) -> dict:
    attempts = [
        attempt for attempt in snapshot["node_attempts"]
        if attempt["node_name"] == node_name and attempt["attempt_status"] == "succeeded"
    ]
    if len(attempts) != 1:
        raise RuntimeError(f"Expected one successful {node_name} attempt, found {len(attempts)}")
    return attempts[0]["output_summary"][field]


def main() -> int:
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-RON",
            "order_number": "DEMO-1004",
            "request_text": CUSTOMER_MESSAGE,
        },
    )
    assert created is not None
    run_id = created["run_id"]
    try:
        waiting = wait_for(run_id, "waiting_for_approval")
        classification = node_output(waiting, "classify_request", "classification")
        claim = classification["device_activation_claim"]
        if claim["status"] != "not_activated" or not claim["verified_in_message"]:
            raise RuntimeError(f"AI did not extract a grounded activation claim: {claim}")
        if claim["supporting_text"].casefold() not in CUSTOMER_MESSAGE.casefold():
            raise RuntimeError(f"AI claim quote was not present in the request: {claim}")

        order = node_output(waiting, "lookup_order", "order_lookup")
        if not any(item["activated_at"] for item in order["items"]):
            raise RuntimeError("Authoritative order evidence did not show activation")

        decision = node_output(waiting, "decide_return", "decision")
        expected_reasons = {
            "ACTIVATION_STATUS_CONFLICT",
            "REFUND_OVER_MANAGER_LIMIT",
        }
        if set(decision["reason_codes"]) != expected_reasons:
            raise RuntimeError(f"Unexpected activation-conflict reasons: {decision}")
        if "ACTIVATED_PHONE_EXCLUDED" in decision["reason_codes"]:
            raise RuntimeError("Conflicting evidence was incorrectly treated as an automatic denial")
        if not decision["facts"]["activation_status_conflict"]:
            raise RuntimeError(f"Decision did not retain the activation conflict: {decision}")

        request_json(
            f"/returns/{run_id}/manager-decision",
            method="POST",
            payload={
                "decision": "approved",
                "decided_by": "manager.activation-smoke",
                "decision_note": "Activation discrepancy was reviewed and approved.",
            },
        )
        completed = wait_for(run_id, "completed")
        if completed["refund"]["refund_status"] != "succeeded":
            raise RuntimeError("Approved activation-conflict workflow did not refund")
        print(
            "PASS: AI extracted Ron's not-activated claim, deterministic rules "
            "found the database conflict, human review resumed, and exactly one refund completed."
        )
        return 0
    finally:
        request_json(f"/returns/{run_id}", method="DELETE")


if __name__ == "__main__":
    raise SystemExit(main())
