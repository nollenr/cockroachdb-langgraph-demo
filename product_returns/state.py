"""Typed state shared by the Product Returns LangGraph nodes."""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict


Intent = Literal["refund", "complaint", "other", "ambiguous"]


class DeviceActivationClaim(TypedDict):
    """A customer assertion extracted by AI and grounded in source text."""

    status: Literal["activated", "not_activated", "unspecified"]
    supporting_text: str
    verified_in_message: bool


class ProductSafetyConcern(TypedDict):
    """A potential safety concern extracted by AI and grounded in source text."""

    status: Literal["present", "unspecified"]
    category: Literal[
        "overheating",
        "smoke_or_fire",
        "electric_shock",
        "injury",
        "property_damage",
        "other",
        "unspecified",
    ]
    supporting_text: str
    verified_in_message: bool


class ClassificationResult(TypedDict):
    """Machine-checkable result produced by the classification node."""

    intent: Intent
    confidence: float
    rationale: str
    needs_clarification: bool
    model: str
    reasoning_effort: str
    device_activation_claim: DeviceActivationClaim
    product_safety_concern: ProductSafetyConcern


class NodeFailure(TypedDict):
    """Serializable failure information for a node that may be retried."""

    node_name: str
    error_code: str
    message: str
    retryable: bool


class OrderItemEvidence(TypedDict):
    """One immutable order-item snapshot returned by order lookup."""

    order_item_id: str
    sku: str
    product_name: str
    product_category: str
    quantity: int
    unit_price: str
    tax_amount: str
    line_total: str
    activated_at: str | None


class OrderLookupResult(TypedDict):
    """Structured order facts used by the later eligibility decision."""

    found: bool
    customer_match: bool
    order_number: str
    order_id: str | None
    order_status: str | None
    currency: str | None
    ordered_at: str | None
    days_since_order: int | None
    refundable_item_total: str | None
    shipping_amount: str | None
    items: list[OrderItemEvidence]


class PolicyCitation(TypedDict):
    """A semantic-search result verified against authoritative policy rows."""

    document_title: str
    policy_key: str
    policy_version: str
    section_heading: str
    clause_key: str
    source_uri: str
    content_sha256: str
    quote: str
    distance_score: float


class PolicyEvidenceResult(TypedDict):
    """Verified policy evidence returned by the retrieval branch."""

    verified: bool
    query: str
    namespace: str
    citations: list[PolicyCitation]


class FraudAssessmentResult(TypedDict):
    """Transparent demo risk signals, not a declaration that fraud occurred."""

    customer_found: bool
    account_status: str | None
    prior_refunded_requests: int
    prior_refunded_amount: str
    risk_score: int
    risk_level: Literal["low", "medium", "high", "unknown"]
    requires_manual_review: bool
    signal_codes: list[str]
    assessment_basis: str


DecisionOutcome = Literal[
    "ineligible",
    "requires_approval",
    "approved_for_refund",
]


class CustomerInsight(TypedDict):
    """Grounded AI observation that is informative but does not route the graph."""

    code: Literal["POTENTIAL_PRODUCT_SAFETY_CONCERN"]
    category: str
    supporting_text: str
    verified_in_message: bool
    follow_up: Literal["recorded_for_product_safety_follow_up"]


class ReturnDecision(TypedDict):
    """Deterministic, auditable eligibility and routing decision."""

    outcome: DecisionOutcome
    next_action: Literal[
        "finish_without_refund",
        "wait_for_manager_approval",
        "issue_refund",
    ]
    eligible: bool
    requires_manager_approval: bool
    reason_codes: list[str]
    explanation: str
    calculated_refund_amount: str
    approved_refund_amount: str | None
    currency: str | None
    policy_citations: list[PolicyCitation]
    customer_insights: list[CustomerInsight]
    customer_acknowledgement: str | None
    facts: dict[str, object]


class ManagerDecision(TypedDict):
    """Durable human response supplied when an interrupted graph resumes."""

    decision: Literal["approved", "rejected"]
    decided_by: str
    decision_note: str | None
    decided_at: str


class ReservedReturnItem(TypedDict):
    """One purchased line quantity protected from duplicate returns."""

    order_item_id: str
    sku: str
    purchased_quantity: int
    requested_quantity: int
    available_before: int


class ReturnReservationResult(TypedDict):
    """Durable outcome of the item-level quantity reservation node."""

    status: Literal["reserved", "conflict"]
    reason_code: Literal["RETURN_QUANTITY_RESERVED", "RETURN_QUANTITY_UNAVAILABLE"]
    explanation: str
    items: list[ReservedReturnItem]


class RefundResult(TypedDict):
    """Idempotent payment-provider result checkpointed by the refund node."""

    refund_id: str
    idempotency_key: str
    payment_provider: str
    provider_refund_id: str
    refund_amount: str
    currency: str
    refund_status: Literal["succeeded"]
    provider_request_count: int


class ReturnWorkflowState(TypedDict):
    """Durable state accumulated as one return request moves through the graph.

    The three evidence results are intentionally independent fields. Later,
    order lookup, policy retrieval, and fraud assessment can update their own
    field without replacing successful results from sibling nodes.
    """

    run_id: str
    thread_id: str
    customer_id: str
    customer_message: str
    order_number: NotRequired[str]
    classification: NotRequired[ClassificationResult]
    order_lookup: NotRequired[OrderLookupResult]
    policy_evidence: NotRequired[PolicyEvidenceResult]
    fraud_assessment: NotRequired[FraudAssessmentResult]
    decision: NotRequired[ReturnDecision]
    return_reservation: NotRequired[ReturnReservationResult]
    manager_decision: NotRequired[ManagerDecision]
    refund_result: NotRequired[RefundResult]
    node_failures: NotRequired[list[NodeFailure]]

