"""LangGraph construction for the Product Returns workflow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from product_returns.approval import await_manager_approval_node
from product_returns.classification import create_classification_node
from product_returns.decision import decide_return_node
from product_returns.graph_version import (
    validate_deployment_graph_version,
    validate_graph_definition,
)
from product_returns.observability import NodeEventRecorder, observable_node
from product_returns.state import ReturnWorkflowState


def _validate_current_graph() -> None:
    """Reject an unregistered graph change or a mismatched deployment."""

    validate_graph_definition()
    validate_deployment_graph_version()


def build_classification_graph(
    chat_model: BaseChatModel,
    model_name: str,
    reasoning_effort: str,
) -> StateGraph:
    """Build the first vertical slice: START -> classify_request -> END."""

    _validate_current_graph()
    builder = StateGraph(ReturnWorkflowState)
    classification_node = create_classification_node(
        chat_model,
        model_name,
        reasoning_effort,
    )
    builder.add_node(
        "classify_request",
        observable_node("classify_request", classification_node),
    )
    builder.add_edge(START, "classify_request")
    builder.add_edge("classify_request", END)
    return builder


def _route_after_classification(state: ReturnWorkflowState) -> str | list[str]:
    """Fan refund requests out; all other intents leave this workflow."""

    classification = state.get("classification")
    if classification is None:
        raise RuntimeError("Classification result is missing")
    if classification["intent"] != "refund":
        return END
    return ["lookup_order", "retrieve_policy", "assess_fraud"]


def build_evidence_graph(
    chat_model: BaseChatModel,
    model_name: str,
    reasoning_effort: str,
    *,
    order_lookup_node: Callable[[ReturnWorkflowState], dict[str, Any]],
    policy_retrieval_node: Callable[[ReturnWorkflowState], dict[str, Any]],
    fraud_assessment_node: Callable[[ReturnWorkflowState], dict[str, Any]],
    evidence_retry_policy: RetryPolicy,
    reservation_node: Callable[[ReturnWorkflowState], dict[str, Any]] | None = None,
    reservation_retry_policy: RetryPolicy | None = None,
    refund_node: Callable[[ReturnWorkflowState], dict[str, Any]] | None = None,
    refund_retry_policy: RetryPolicy | None = None,
    node_event_recorder: NodeEventRecorder | None = None,
) -> StateGraph:
    """Build the durable return graph through optional refund execution."""

    def route_after_decision(state: ReturnWorkflowState) -> str:
        decision = state.get("decision")
        if decision is None:
            raise RuntimeError("Return decision is missing")
        if decision["outcome"] == "requires_approval":
            return (
                "reserve_return_items"
                if reservation_node is not None
                else "await_manager_approval"
            )
        if decision["outcome"] == "approved_for_refund" and refund_node is not None:
            return (
                "reserve_return_items"
                if reservation_node is not None
                else "issue_refund"
            )
        return END

    def route_after_reservation(state: ReturnWorkflowState) -> str:
        reservation = state.get("return_reservation")
        if reservation is None:
            raise RuntimeError("Return quantity reservation result is missing")
        if reservation["status"] == "conflict":
            return END
        decision = state.get("decision")
        if decision is None:
            raise RuntimeError("Return decision is missing after reservation")
        if decision["outcome"] == "requires_approval":
            return "await_manager_approval"
        if decision["outcome"] == "approved_for_refund" and refund_node is not None:
            return "issue_refund"
        return END

    def route_after_approval(state: ReturnWorkflowState) -> str:
        manager = state.get("manager_decision")
        if manager is None:
            raise RuntimeError("Manager decision is missing after approval resume")
        if manager["decision"] == "approved" and refund_node is not None:
            return "issue_refund"
        return END

    _validate_current_graph()
    builder = StateGraph(ReturnWorkflowState)
    classification_node = create_classification_node(
        chat_model,
        model_name,
        reasoning_effort,
    )
    builder.add_node(
        "classify_request",
        observable_node("classify_request", classification_node, node_event_recorder),
    )
    builder.add_node(
        "lookup_order",
        observable_node("lookup_order", order_lookup_node, node_event_recorder),
        retry_policy=evidence_retry_policy,
    )
    builder.add_node(
        "retrieve_policy",
        observable_node("retrieve_policy", policy_retrieval_node, node_event_recorder),
        retry_policy=evidence_retry_policy,
    )
    builder.add_node(
        "assess_fraud",
        observable_node("assess_fraud", fraud_assessment_node, node_event_recorder),
        retry_policy=evidence_retry_policy,
    )
    builder.add_node(
        "decide_return",
        observable_node("decide_return", decide_return_node, node_event_recorder),
    )
    builder.add_node("await_manager_approval", await_manager_approval_node)
    if reservation_node is not None:
        builder.add_node(
            "reserve_return_items",
            observable_node("reserve_return_items", reservation_node, node_event_recorder),
            retry_policy=reservation_retry_policy,
        )
    if refund_node is not None:
        builder.add_node(
            "issue_refund",
            observable_node("issue_refund", refund_node, node_event_recorder),
            retry_policy=refund_retry_policy,
        )
    builder.add_edge(START, "classify_request")
    builder.add_conditional_edges("classify_request", _route_after_classification)
    builder.add_edge("lookup_order", "decide_return")
    builder.add_edge("retrieve_policy", "decide_return")
    builder.add_edge("assess_fraud", "decide_return")
    builder.add_conditional_edges("decide_return", route_after_decision)
    if reservation_node is not None:
        builder.add_conditional_edges("reserve_return_items", route_after_reservation)
    builder.add_conditional_edges("await_manager_approval", route_after_approval)
    if refund_node is not None:
        builder.add_edge("issue_refund", END)
    return builder

