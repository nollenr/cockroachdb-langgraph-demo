#!/usr/bin/env python3
"""Prove Bob's recent eligible order is reviewed solely for risk signals."""

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
            raise RuntimeError(f"Fraud-review workflow reached {last['run_status']}: {last}")
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
            "customer_external_id": "CUST-BOB",
            "order_number": "DEMO-1007",
            "request_text": "I want to return the coffee maker from order DEMO-1007. It is unused and in the original packaging.",
        },
    )
    assert created is not None
    run_id = created["run_id"]
    try:
        waiting = wait_for(run_id, "waiting_for_approval")
        fraud = node_output(waiting, "assess_fraud", "fraud_assessment")
        decision = node_output(waiting, "decide_return", "decision")
        if fraud["risk_score"] != 90 or fraud["risk_level"] != "high":
            raise RuntimeError(f"Unexpected Bob risk assessment: {fraud}")
        expected_signals = {"ACCOUNT_RESTRICTED", "THREE_OR_MORE_PRIOR_REFUNDS"}
        if set(fraud["signal_codes"]) != expected_signals:
            raise RuntimeError(f"Unexpected Bob risk signals: {fraud}")
        if decision["reason_codes"] != ["FRAUD_REVIEW_REQUIRED"]:
            raise RuntimeError(f"Review was not caused solely by fraud signals: {decision}")
        if decision["calculated_refund_amount"] != "140.39":
            raise RuntimeError(f"Unexpected refund amount: {decision}")

        request_json(
            f"/returns/{run_id}/manager-decision",
            method="POST",
            payload={
                "decision": "approved",
                "decided_by": "manager.fraud-smoke",
                "decision_note": "Approved after reviewing the transparent demo risk signals.",
            },
        )
        completed = wait_for(run_id, "completed")
        if completed["refund"]["refund_status"] != "succeeded":
            raise RuntimeError("Approved fraud-review workflow did not refund")
        print(
            "PASS: DEMO-1007 scored 90 from restricted-account and prior-refund "
            "signals, required approval solely for risk, and completed one refund."
        )
        return 0
    finally:
        request_json(f"/returns/{run_id}", method="DELETE")


if __name__ == "__main__":
    raise SystemExit(main())
