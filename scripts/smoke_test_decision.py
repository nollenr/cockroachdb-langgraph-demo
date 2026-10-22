#!/usr/bin/env python3
"""Exercise deterministic decision outcomes and their audit evidence."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.decision import decide_return_node  # noqa: E402
from product_returns.graph_version import validate_graph_definition  # noqa: E402


CLAUSES = {
    "RET-ELIGIBILITY-001": "Return Eligibility and Time Window",
    "RET-CONDITION-001": "Product Condition",
    "RET-PROOF-001": "Proof of Purchase",
    "RET-EXCEPTION-001": "Non-Returnable Products and Exceptions",
    "RET-AMOUNT-001": "Refund Amount",
    "RET-PAYMENT-001": "Refund Method and Timing",
    "RET-APPROVAL-001": "Manual Review and Manager Approval",
    "RET-RIGHTS-001": "Customer Rights and Support",
}


def citation(clause_key: str) -> dict[str, Any]:
    return {
        "document_title": "Standard Return and Refund Policy",
        "policy_key": "standard-returns",
        "policy_version": "1.0",
        "section_heading": CLAUSES[clause_key],
        "clause_key": clause_key,
        "source_uri": "policies/standard-return-policy-v1.md",
        "content_sha256": "test-policy-hash",
        "quote": f"Verified text for {clause_key}.",
        "distance_score": 0.1,
    }


BASE_STATE: dict[str, Any] = {
    "run_id": "00000000-0000-0000-0000-000000000001",
    "thread_id": "decision-smoke",
    "customer_id": "CUST-RON",
    "customer_message": "I want to return my order.",
    "classification": {
        "intent": "refund",
        "confidence": 0.99,
        "rationale": "The customer explicitly requested a return.",
        "needs_clarification": False,
        "model": "test-model",
        "reasoning_effort": "none",
        "device_activation_claim": {
            "status": "unspecified",
            "supporting_text": "",
            "verified_in_message": False,
        },
        "product_safety_concern": {
            "status": "unspecified",
            "category": "unspecified",
            "supporting_text": "",
            "verified_in_message": False,
        },
    },
    "order_lookup": {
        "found": True,
        "customer_match": True,
        "order_number": "DEMO-1001",
        "order_id": "30000000-0000-4000-8000-000000000001",
        "order_status": "delivered",
        "currency": "USD",
        "ordered_at": "2026-10-10T00:00:00+00:00",
        "days_since_order": 10,
        "refundable_item_total": "53.99",
        "shipping_amount": "0.00",
        "items": [
            {
                "order_item_id": "40000000-0000-4000-8000-000000000001",
                "sku": "TOAST-2SL",
                "product_name": "Two-Slice Toaster",
                "product_category": "small_appliance",
                "quantity": 1,
                "unit_price": "49.99",
                "tax_amount": "4.00",
                "line_total": "53.99",
                "activated_at": None,
            }
        ],
    },
    "policy_evidence": {
        "verified": True,
        "query": "I want to return my order.",
        "namespace": "standard-returns:1.0",
        "citations": [citation(key) for key in CLAUSES],
    },
    "fraud_assessment": {
        "customer_found": True,
        "account_status": "active",
        "prior_refunded_requests": 0,
        "prior_refunded_amount": "0.00",
        "risk_score": 0,
        "risk_level": "low",
        "requires_manual_review": False,
        "signal_codes": [],
        "assessment_basis": "demo_rules_v1",
    },
}


def assert_case(
    name: str,
    state: dict[str, Any],
    expected_outcome: str,
    expected_reason: str,
) -> None:
    decision = decide_return_node(state)["decision"]
    if decision["outcome"] != expected_outcome:
        raise RuntimeError(
            f"{name}: expected {expected_outcome}, got {decision['outcome']}"
        )
    if expected_reason not in decision["reason_codes"]:
        raise RuntimeError(
            f"{name}: missing {expected_reason}: {decision['reason_codes']}"
        )
    if not decision["explanation"]:
        raise RuntimeError(f"{name}: explanation is empty")
    cited_keys = {item["clause_key"] for item in decision["policy_citations"]}
    required_by_reason = {
        "ELIGIBLE_STANDARD_RETURN": "RET-ELIGIBILITY-001",
        "REFUND_OVER_MANAGER_LIMIT": "RET-APPROVAL-001",
        "FRAUD_REVIEW_REQUIRED": "RET-APPROVAL-001",
        "GIFT_CARD_FINAL_SALE": "RET-EXCEPTION-001",
        "ACTIVATED_PHONE_EXCLUDED": "RET-EXCEPTION-001",
        "ACTIVATION_STATUS_CONFLICT": "RET-APPROVAL-001",
        "OUTSIDE_RETURN_WINDOW": "RET-ELIGIBILITY-001",
    }
    required_clause = required_by_reason.get(expected_reason)
    if required_clause is not None and required_clause not in cited_keys:
        raise RuntimeError(f"{name}: missing policy citation {required_clause}")
    print(
        f"PASS {name}: {decision['outcome']} / "
        + ",".join(decision["reason_codes"])
    )


def main() -> int:
    validate_graph_definition()

    assert_case(
        "eligible_under_500",
        deepcopy(BASE_STATE),
        "approved_for_refund",
        "ELIGIBLE_STANDARD_RETURN",
    )

    safety_concern = deepcopy(BASE_STATE)
    safety_concern["customer_message"] = (
        "I want to return the toaster. It gets really hot and may scorch my countertop."
    )
    safety_concern["classification"]["product_safety_concern"] = {
        "status": "present",
        "category": "overheating",
        "supporting_text": "gets really hot and may scorch my countertop",
        "verified_in_message": True,
    }
    safety_decision = decide_return_node(safety_concern)["decision"]
    if safety_decision["outcome"] != "approved_for_refund":
        raise RuntimeError("safety_concern: insight changed refund eligibility")
    if safety_decision["reason_codes"] != ["ELIGIBLE_STANDARD_RETURN"]:
        raise RuntimeError("safety_concern: insight changed deterministic routing")
    if safety_decision["customer_insights"] != [
        {
            "code": "POTENTIAL_PRODUCT_SAFETY_CONCERN",
            "category": "overheating",
            "supporting_text": "gets really hot and may scorch my countertop",
            "verified_in_message": True,
            "follow_up": "recorded_for_product_safety_follow_up",
        }
    ]:
        raise RuntimeError("safety_concern: expected grounded customer insight")
    if "recorded it for product-safety follow-up" not in (
        safety_decision["customer_acknowledgement"] or ""
    ):
        raise RuntimeError("safety_concern: acknowledgement is missing")
    print("PASS safety_concern: approved refund plus grounded acknowledgement")

    over_limit = deepcopy(BASE_STATE)
    over_limit["order_lookup"]["refundable_item_total"] = "700.92"
    assert_case(
        "manager_threshold",
        over_limit,
        "requires_approval",
        "REFUND_OVER_MANAGER_LIMIT",
    )

    fraud_review = deepcopy(BASE_STATE)
    fraud_review["fraud_assessment"].update(
        {
            "risk_score": 90,
            "risk_level": "high",
            "requires_manual_review": True,
            "signal_codes": ["ACCOUNT_RESTRICTED"],
        }
    )
    assert_case(
        "fraud_review",
        fraud_review,
        "requires_approval",
        "FRAUD_REVIEW_REQUIRED",
    )

    gift_card = deepcopy(BASE_STATE)
    gift_card["order_lookup"]["items"][0]["product_category"] = "gift_card"
    assert_case(
        "gift_card",
        gift_card,
        "ineligible",
        "GIFT_CARD_FINAL_SALE",
    )

    activated_phone = deepcopy(BASE_STATE)
    activated_phone["order_lookup"]["items"][0].update(
        {
            "product_category": "mobile_phone",
            "activated_at": "2026-10-14T00:00:00+00:00",
        }
    )
    assert_case(
        "activated_phone",
        activated_phone,
        "ineligible",
        "ACTIVATED_PHONE_EXCLUDED",
    )

    activation_conflict = deepcopy(activated_phone)
    activation_conflict["customer_message"] = (
        "I want to return the phone. It has not been activated."
    )
    activation_conflict["classification"]["device_activation_claim"] = {
        "status": "not_activated",
        "supporting_text": "has not been activated",
        "verified_in_message": True,
    }
    conflict_decision = decide_return_node(activation_conflict)["decision"]
    if conflict_decision["outcome"] != "requires_approval":
        raise RuntimeError(
            "activation_conflict: expected requires_approval, got "
            f"{conflict_decision['outcome']}"
        )
    if conflict_decision["reason_codes"] != ["ACTIVATION_STATUS_CONFLICT"]:
        raise RuntimeError(
            "activation_conflict: customer claim did not replace automatic denial: "
            f"{conflict_decision['reason_codes']}"
        )
    cited_keys = {
        item["clause_key"] for item in conflict_decision["policy_citations"]
    }
    if cited_keys != {"RET-EXCEPTION-001", "RET-APPROVAL-001"}:
        raise RuntimeError(
            f"activation_conflict: unexpected citations {sorted(cited_keys)}"
        )
    if not conflict_decision["facts"]["activation_status_conflict"]:
        raise RuntimeError("activation_conflict: conflict fact was not recorded")
    print(
        "PASS activation_conflict: requires_approval / "
        "ACTIVATION_STATUS_CONFLICT"
    )

    expired = deepcopy(BASE_STATE)
    expired["order_lookup"]["days_since_order"] = 45
    assert_case(
        "outside_window",
        expired,
        "ineligible",
        "OUTSIDE_RETURN_WINDOW",
    )

    missing_order = deepcopy(BASE_STATE)
    missing_order["order_lookup"].update(
        {
            "found": False,
            "customer_match": False,
            "order_id": None,
            "order_status": None,
            "currency": None,
            "ordered_at": None,
            "days_since_order": None,
            "refundable_item_total": None,
            "items": [],
        }
    )
    assert_case(
        "order_not_found",
        missing_order,
        "ineligible",
        "ORDER_NOT_FOUND",
    )

    print("Deterministic return-decision smoke test passed 9/9 scenarios.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Decision smoke test failed: {error}", file=sys.stderr)
        raise

