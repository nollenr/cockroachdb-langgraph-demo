"""Request-intent classification node for the Product Returns graph."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from product_returns.state import ClassificationResult, ReturnWorkflowState


CLASSIFICATION_SYSTEM_PROMPT = """You classify one customer-service message.

Return exactly one intent:
- refund: the customer explicitly asks to return, exchange, or receive a refund
  for a purchased product.
- complaint: the customer expresses dissatisfaction or reports a product
  problem but does not ask for a return, exchange, or refund. Classify a
  question about potentially concerning product behavior as complaint even
  when the customer phrases it as a question rather than a statement.
- other: the customer clearly requests a different service, such as order
  tracking or an address change.
- ambiguous: the message does not clearly establish one of the other intents.

Do not decide return eligibility, policy coverage, fraud risk, approval, or
refund amount. Those belong to later graph nodes. Base the classification only
on the customer's message. Keep the rationale to one short sentence.

Also extract whether the customer explicitly says a device is activated or not
activated. Use "unspecified" when no explicit activation statement appears.
For an explicit claim, supporting_text must be the shortest exact verbatim
substring that supports it. For "unspecified", supporting_text must be empty.

Also extract a potential product-safety concern only when the customer
explicitly describes a risk of overheating, smoke, fire, electric shock,
physical injury, or property damage. This is a customer insight, not an
eligibility decision. Use "unspecified" when no explicit safety concern
appears. For a present concern, supporting_text must be the shortest exact
verbatim substring that supports it. For "unspecified", category must be
"unspecified" and supporting_text must be empty.
"""


class DeviceActivationClaimDecision(BaseModel):
    """Structured activation assertion extracted from the customer message."""

    status: Literal["activated", "not_activated", "unspecified"]
    supporting_text: str = Field(max_length=200)


class ProductSafetyConcernDecision(BaseModel):
    """Potential safety concern extracted from the customer message."""

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
    supporting_text: str = Field(max_length=300)


class ClassificationDecision(BaseModel):
    """Structured model response before it is written to graph state."""

    intent: Literal["refund", "complaint", "other", "ambiguous"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=300)
    device_activation_claim: DeviceActivationClaimDecision
    product_safety_concern: ProductSafetyConcernDecision


def create_classification_node(
    chat_model: BaseChatModel,
    model_name: str,
    reasoning_effort: str,
) -> Callable[[ReturnWorkflowState], dict[str, ClassificationResult]]:
    """Bind a structured classifier and return a LangGraph node function."""

    structured_model = chat_model.with_structured_output(
        ClassificationDecision,
        method="json_schema",
        strict=True,
    )

    def classify_request(
        state: ReturnWorkflowState,
    ) -> dict[str, ClassificationResult]:
        message = state["customer_message"].strip()
        if not message:
            raise ValueError("customer_message must not be empty")

        decision = structured_model.invoke(
            [
                SystemMessage(content=CLASSIFICATION_SYSTEM_PROMPT),
                HumanMessage(content=message),
            ]
        )
        if not isinstance(decision, ClassificationDecision):
            raise TypeError("Classifier did not return ClassificationDecision")

        claim_status = decision.device_activation_claim.status
        supporting_text = decision.device_activation_claim.supporting_text.strip()
        claim_is_grounded = (
            claim_status != "unspecified"
            and bool(supporting_text)
            and supporting_text.casefold() in message.casefold()
        )
        if not claim_is_grounded:
            claim_status = "unspecified"
            supporting_text = ""

        safety_status = decision.product_safety_concern.status
        safety_category = decision.product_safety_concern.category
        safety_supporting_text = (
            decision.product_safety_concern.supporting_text.strip()
        )
        safety_is_grounded = (
            safety_status == "present"
            and safety_category != "unspecified"
            and bool(safety_supporting_text)
            and safety_supporting_text.casefold() in message.casefold()
        )
        if not safety_is_grounded:
            safety_status = "unspecified"
            safety_category = "unspecified"
            safety_supporting_text = ""

        result: ClassificationResult = {
            "intent": decision.intent,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "needs_clarification": decision.intent == "ambiguous",
            "model": model_name,
            "reasoning_effort": reasoning_effort,
            "device_activation_claim": {
                "status": claim_status,
                "supporting_text": supporting_text,
                "verified_in_message": claim_is_grounded,
            },
            "product_safety_concern": {
                "status": safety_status,
                "category": safety_category,
                "supporting_text": safety_supporting_text,
                "verified_in_message": safety_is_grounded,
            },
        }
        return {"classification": result}

    return classify_request

