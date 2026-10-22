"""Deterministic return eligibility, approval, and rejection decisions."""

from __future__ import annotations

from decimal import Decimal

from product_returns.state import (
    CustomerInsight,
    PolicyCitation,
    ReturnDecision,
    ReturnWorkflowState,
)


RETURN_WINDOW_DAYS = 30
MANAGER_APPROVAL_THRESHOLD = Decimal("500.00")

REASON_EXPLANATIONS = {
    "ORDER_NOT_FOUND": "The order could not be found for this customer.",
    "CUSTOMER_ORDER_MISMATCH": "The order does not belong to this customer.",
    "ORDER_NOT_DELIVERED": "Only delivered orders are eligible for this return flow.",
    "OUTSIDE_RETURN_WINDOW": "The purchase is outside the 30-day return window.",
    "GIFT_CARD_FINAL_SALE": "Gift cards are final sale under the return policy.",
    "ACTIVATED_PHONE_EXCLUDED": (
        "Activated mobile phones are excluded from standard returns."
    ),
    "ACTIVATION_STATUS_CONFLICT": (
        "We found conflicting activation information. Our records indicate that "
        "this phone was activated, while your request says it was not. This "
        "return requires manual review."
    ),
    "NO_REFUNDABLE_ITEMS": "The request contains no refundable item amount.",
    "FRAUD_REVIEW_REQUIRED": "The account signals require manager review.",
    "REFUND_OVER_MANAGER_LIMIT": (
        "The calculated refund is greater than the $500 manager threshold."
    ),
    "ELIGIBLE_STANDARD_RETURN": "The request meets the standard return rules.",
}

REASON_CLAUSES = {
    "OUTSIDE_RETURN_WINDOW": {"RET-ELIGIBILITY-001"},
    "GIFT_CARD_FINAL_SALE": {"RET-EXCEPTION-001"},
    "ACTIVATED_PHONE_EXCLUDED": {"RET-EXCEPTION-001"},
    "ACTIVATION_STATUS_CONFLICT": {
        "RET-EXCEPTION-001",
        "RET-APPROVAL-001",
    },
    "NO_REFUNDABLE_ITEMS": {"RET-AMOUNT-001"},
    "REFUND_OVER_MANAGER_LIMIT": {"RET-APPROVAL-001", "RET-AMOUNT-001"},
    "FRAUD_REVIEW_REQUIRED": {"RET-APPROVAL-001"},
    "ELIGIBLE_STANDARD_RETURN": {
        "RET-ELIGIBILITY-001",
        "RET-AMOUNT-001",
        "RET-PAYMENT-001",
    },
}


def _money(value: Decimal | str | int) -> str:
    return f"{Decimal(value):.2f}"


def _safety_acknowledgement(category: str) -> str:
    descriptions = {
        "overheating": "the product may be getting dangerously hot",
        "smoke_or_fire": "the product may present a smoke or fire risk",
        "electric_shock": "the product may present an electrical-shock risk",
        "injury": "the product may present an injury risk",
        "property_damage": "the product may cause property damage",
        "other": "the product may present a safety concern",
    }
    description = descriptions.get(category, "the product may present a safety concern")
    return (
        f"We heard your concern that {description}. "
        "We recorded it for product-safety follow-up."
    )


def _required_policy_citations(
    citations: list[PolicyCitation],
    reason_codes: list[str],
) -> list[PolicyCitation]:
    required_keys: set[str] = set()
    for reason_code in reason_codes:
        required_keys.update(REASON_CLAUSES.get(reason_code, set()))
    selected = [
        citation
        for citation in citations
        if citation["clause_key"] in required_keys
    ]
    found_keys = {citation["clause_key"] for citation in selected}
    missing = required_keys - found_keys
    if missing:
        raise RuntimeError(
            "Verified policy evidence is missing decision clauses: "
            + ", ".join(sorted(missing))
        )
    return selected


def decide_return_node(state: ReturnWorkflowState) -> dict[str, ReturnDecision]:
    """Combine independent evidence into one explainable business decision."""

    order = state.get("order_lookup")
    policy = state.get("policy_evidence")
    fraud = state.get("fraud_assessment")
    if order is None or policy is None or fraud is None:
        raise RuntimeError("Decision requires order, policy, and fraud evidence")
    if not policy["verified"]:
        raise RuntimeError("Decision requires verified policy evidence")

    ineligible_reasons: list[str] = []
    approval_reasons: list[str] = []
    classification = state.get("classification")
    activation_claim = (
        classification.get("device_activation_claim")
        if classification is not None
        else None
    )
    safety_concern = (
        classification.get("product_safety_concern")
        if classification is not None
        else None
    )
    verified_safety_concern = bool(
        safety_concern
        and safety_concern["status"] == "present"
        and safety_concern["verified_in_message"]
    )
    customer_claims_not_activated = bool(
        activation_claim
        and activation_claim["status"] == "not_activated"
        and activation_claim["verified_in_message"]
    )
    activated_phone_items = [
        item
        for item in order["items"]
        if item["product_category"] == "mobile_phone"
        and item["activated_at"] is not None
    ]
    activation_status_conflict = bool(
        activated_phone_items and customer_claims_not_activated
    )

    if not order["found"]:
        ineligible_reasons.append("ORDER_NOT_FOUND")
    elif not order["customer_match"]:
        ineligible_reasons.append("CUSTOMER_ORDER_MISMATCH")
    else:
        if order["order_status"] != "delivered":
            ineligible_reasons.append("ORDER_NOT_DELIVERED")
        if (
            order["days_since_order"] is not None
            and order["days_since_order"] > RETURN_WINDOW_DAYS
        ):
            ineligible_reasons.append("OUTSIDE_RETURN_WINDOW")
        if any(item["product_category"] == "gift_card" for item in order["items"]):
            ineligible_reasons.append("GIFT_CARD_FINAL_SALE")
        if activated_phone_items and not activation_status_conflict:
            ineligible_reasons.append("ACTIVATED_PHONE_EXCLUDED")

    calculated_amount = Decimal(order["refundable_item_total"] or "0.00")
    if order["found"] and calculated_amount <= 0:
        ineligible_reasons.append("NO_REFUNDABLE_ITEMS")

    if fraud["requires_manual_review"]:
        approval_reasons.append("FRAUD_REVIEW_REQUIRED")
    if activation_status_conflict:
        approval_reasons.append("ACTIVATION_STATUS_CONFLICT")
    if calculated_amount > MANAGER_APPROVAL_THRESHOLD:
        approval_reasons.append("REFUND_OVER_MANAGER_LIMIT")

    if ineligible_reasons:
        outcome = "ineligible"
        next_action = "finish_without_refund"
        reason_codes = ineligible_reasons
        eligible = False
        requires_approval = False
        approved_amount = None
    elif approval_reasons:
        outcome = "requires_approval"
        next_action = "wait_for_manager_approval"
        reason_codes = approval_reasons
        eligible = True
        requires_approval = True
        approved_amount = None
    else:
        outcome = "approved_for_refund"
        next_action = "issue_refund"
        reason_codes = ["ELIGIBLE_STANDARD_RETURN"]
        eligible = True
        requires_approval = False
        approved_amount = _money(calculated_amount)

    citations = _required_policy_citations(policy["citations"], reason_codes)
    explanation = " ".join(REASON_EXPLANATIONS[code] for code in reason_codes)
    customer_insights: list[CustomerInsight] = []
    customer_acknowledgement: str | None = None
    if verified_safety_concern and safety_concern is not None:
        customer_acknowledgement = _safety_acknowledgement(
            safety_concern["category"]
        )
        customer_insights.append(
            {
                "code": "POTENTIAL_PRODUCT_SAFETY_CONCERN",
                "category": safety_concern["category"],
                "supporting_text": safety_concern["supporting_text"],
                "verified_in_message": True,
                "follow_up": "recorded_for_product_safety_follow_up",
            }
        )
    decision: ReturnDecision = {
        "outcome": outcome,
        "next_action": next_action,
        "eligible": eligible,
        "requires_manager_approval": requires_approval,
        "reason_codes": reason_codes,
        "explanation": explanation,
        "calculated_refund_amount": _money(calculated_amount),
        "approved_refund_amount": approved_amount,
        "currency": order["currency"],
        "policy_citations": citations,
        "customer_insights": customer_insights,
        "customer_acknowledgement": customer_acknowledgement,
        "facts": {
            "order_number": order["order_number"],
            "order_status": order["order_status"],
            "days_since_order": order["days_since_order"],
            "return_window_days": RETURN_WINDOW_DAYS,
            "item_categories": [
                item["product_category"] for item in order["items"]
            ],
            "customer_device_activation_claim": activation_claim,
            "recorded_activation_timestamps": [
                item["activated_at"] for item in activated_phone_items
            ],
            "activation_status_conflict": activation_status_conflict,
            "customer_product_safety_concern": safety_concern,
            "fraud_risk_score": fraud["risk_score"],
            "fraud_risk_level": fraud["risk_level"],
            "fraud_signal_codes": fraud["signal_codes"],
            "manager_threshold": _money(MANAGER_APPROVAL_THRESHOLD),
        },
    }
    return {"decision": decision}
