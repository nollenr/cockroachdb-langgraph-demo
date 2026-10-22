"""LangGraph human-approval interrupt and resume node."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from langgraph.types import interrupt

from product_returns.state import ManagerDecision, ReturnWorkflowState


def await_manager_approval_node(
    state: ReturnWorkflowState,
) -> dict[str, ManagerDecision]:
    """Pause durably and return the validated manager response after resume.

    LangGraph restarts this node when a Command(resume=...) arrives. Code before
    interrupt() must therefore remain side-effect free; all database writes are
    performed by the surrounding application transaction layer.
    """

    decision = state.get("decision")
    if decision is None or decision["outcome"] != "requires_approval":
        raise RuntimeError("Manager approval interrupt requires an approval decision")

    response = interrupt(
        {
            "kind": "manager_return_approval",
            "run_id": state["run_id"],
            "refund_amount": decision["calculated_refund_amount"],
            "currency": decision["currency"],
            "reason_codes": decision["reason_codes"],
            "explanation": decision["explanation"],
            "policy_citations": decision["policy_citations"],
        }
    )
    if not isinstance(response, Mapping):
        raise ValueError("Manager approval response must be an object")
    manager_decision = response.get("decision")
    decided_by = response.get("decided_by")
    decided_at = response.get("decided_at")
    decision_note = response.get("decision_note")
    if manager_decision not in ("approved", "rejected"):
        raise ValueError("Manager decision must be 'approved' or 'rejected'")
    if not isinstance(decided_by, str) or not decided_by.strip():
        raise ValueError("Manager decision requires decided_by")
    if not isinstance(decided_at, str) or not decided_at:
        raise ValueError("Manager decision requires decided_at")
    if decision_note is not None and not isinstance(decision_note, str):
        raise ValueError("Manager decision_note must be text or null")

    return {
        "manager_decision": cast(
            ManagerDecision,
            {
                "decision": manager_decision,
                "decided_by": decided_by.strip(),
                "decision_note": decision_note,
                "decided_at": decided_at,
            },
        )
    }
