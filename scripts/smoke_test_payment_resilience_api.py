#!/usr/bin/env python3
"""Prove presenter-controlled recovery after provider success through Next.js."""

from __future__ import annotations

import json
import os
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import UUID


API_URL = os.environ["RETURNFLOW_SMOKE_API_URL"].rstrip("/")


def request_json(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    request = Request(
        f"{API_URL}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        method=method,
        headers={"content-type": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        return json.load(response) if response.status != 204 else {}


def wait_for(run_id: UUID, status: str, timeout: float = 90) -> dict:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        snapshot = request_json(f"/returns/{run_id}")
        if snapshot["run_status"] == status:
            return snapshot
        if snapshot["run_status"] in {"completed", "rejected", "failed"}:
            raise RuntimeError(f"Unexpected terminal status {snapshot['run_status']}")
        sleep(0.5)
    raise RuntimeError(f"Run did not reach {status} within {timeout} seconds")


def main() -> int:
    created = request_json(
        "/returns",
        method="POST",
        payload={
            "customer_external_id": "CUST-RON",
            "order_number": "DEMO-1001",
            "request_text": "I want to return the toaster from order DEMO-1001.",
            "failure_node": "issue_refund",
        },
    )
    run_id = UUID(created["run_id"])
    try:
        paused = wait_for(run_id, "retry_wait")
        provider = paused["provider_refund"]
        key = f"product-returns:{run_id}:refund:v1"
        if provider is None or provider["provider_refund_count"] != 1 or provider["request_count"] != 1 or provider["idempotency_key"] != key:
            raise RuntimeError("Provider did not persist exactly one keyed refund before failure")
        if paused["failure_injection"]["injection_status"] != "triggered":
            raise RuntimeError("One-shot payment failure was not durably triggered")
        if paused["lease_owner"] is not None or paused["next_attempt_at"] is not None:
            raise RuntimeError("Paused workflow kept a lease or automatic retry")
        if paused["refund"]["refund_status"] != "processing":
            raise RuntimeError("Local refund completed before the injected worker failure")
        failed = [a for a in paused["node_attempts"] if a["node_name"] == "issue_refund"]
        if len(failed) != 1 or failed[0]["attempt_status"] != "retryable_failure":
            raise RuntimeError("Payment node failure was not recorded once")
        sleep(2)
        still_paused = request_json(f"/returns/{run_id}")
        if still_paused["lease_generation"] != 1 or still_paused["provider_refund"]["request_count"] != 1:
            raise RuntimeError("Dispatcher retried the payment without presenter action")
        sql = request_json(f"/returns/{run_id}/inspection-sql")["sql"]
        if str(run_id) not in sql or "demo_payment_provider_refunds" not in sql or "refund_attempts" not in sql:
            raise RuntimeError("Inspection SQL omitted payment evidence")

        request_json(f"/returns/{run_id}/resume", method="POST", payload={})
        done = wait_for(run_id, "completed")
        final_provider = done["provider_refund"]
        if final_provider["provider_refund_count"] != 1 or final_provider["provider_refund_id"] != provider["provider_refund_id"] or final_provider["request_count"] != 2:
            raise RuntimeError("Second provider request did not return the original refund")
        if done["refund"]["provider_refund_id"] != str(provider["provider_refund_id"]):
            raise RuntimeError("Local completion did not use the original provider refund")
        if done["lease_generation"] != 2:
            raise RuntimeError("Resume did not use a new worker generation")
        attempts = [a["attempt_status"] for a in done["refund_attempts"]]
        if attempts != ["retryable_failure", "succeeded"]:
            raise RuntimeError(f"Unexpected local refund attempts: {attempts}")
        node_attempts = [a["attempt_status"] for a in done["node_attempts"] if a["node_name"] == "issue_refund"]
        if node_attempts != ["retryable_failure", "succeeded"]:
            raise RuntimeError(f"Unexpected payment node attempts: {node_attempts}")
        events = {event["event_type"] for event in done["audit_events"]}
        if not {"injected_failure_paused", "workflow_recovery_requested", "workflow_recovery_worker_claimed", "refund_succeeded"}.issubset(events):
            raise RuntimeError("Payment recovery audit sequence is incomplete")
        print("PASS: one provider refund, two requests, zero duplicate payments; manual generation-2 recovery and inspection SQL verified.")
        return 0
    finally:
        request_json(f"/returns/{run_id}", method="DELETE")


if __name__ == "__main__":
    raise SystemExit(main())
