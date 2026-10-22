"""Independent evidence nodes for the Product Returns LangGraph."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
from langchain_cockroachdb import CockroachDBVectorStore
from psycopg.rows import dict_row

from product_returns.state import (
    FraudAssessmentResult,
    OrderItemEvidence,
    OrderLookupResult,
    PolicyCitation,
    PolicyEvidenceResult,
    ReturnWorkflowState,
)


ORDER_NUMBER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b", re.IGNORECASE)
REQUIRED_POLICY_METADATA = {
    "document_title",
    "policy_key",
    "policy_version",
    "section_heading",
    "clause_key",
    "source_uri",
    "content_sha256",
    "chunk_index",
    "embedding_model",
    "embedding_dimensions",
    "return_policy_id",
    "policy_clause_id",
}

ORDER_LOOKUP_SQL = """
SELECT
    o.order_id,
    o.order_number,
    o.order_status,
    o.currency,
    o.shipping_amount,
    o.ordered_at,
    oi.order_item_id,
    oi.sku,
    oi.product_name,
    oi.product_category,
    oi.quantity,
    oi.unit_price,
    oi.tax_amount,
    oi.line_total,
    oi.activated_at
FROM customers AS c
JOIN orders AS o
  ON o.customer_id = c.customer_id
JOIN order_items AS oi
  ON oi.order_id = o.order_id
WHERE c.external_customer_id = %s
  AND o.order_number = %s
ORDER BY oi.order_item_id
"""

AUTHORITATIVE_POLICY_SQL = """
SELECT
    rp.return_policy_id,
    rp.title,
    rp.policy_key,
    rp.policy_version,
    rp.source_uri,
    rp.content_sha256,
    pc.policy_clause_id,
    pc.clause_key,
    pc.clause_text
FROM return_policies AS rp
JOIN policy_clauses AS pc
  ON pc.return_policy_id = rp.return_policy_id
WHERE rp.policy_key = %s
  AND rp.policy_version = %s
  AND rp.policy_status = 'active'
ORDER BY pc.display_order
"""

FRAUD_ASSESSMENT_SQL = """
SELECT
    c.customer_id,
    c.external_customer_id,
    c.account_status,
    count(DISTINCT rr.return_request_id) AS prior_refunded_requests,
    COALESCE(sum(ri.requested_refund_amount), 0)::DECIMAL(18, 2)
        AS prior_refunded_amount
FROM customers AS c
LEFT JOIN return_requests AS rr
  ON rr.customer_id = c.customer_id
 AND rr.request_status = 'refunded'
LEFT JOIN return_items AS ri
  ON ri.return_request_id = rr.return_request_id
WHERE c.external_customer_id = %s
GROUP BY c.customer_id, c.external_customer_id, c.account_status
"""


class TransientEvidenceError(RuntimeError):
    """A retryable transient branch failure used by runtime code and tests."""


class PolicyVerificationError(RuntimeError):
    """Retrieved policy evidence did not match its authoritative source."""


def retryable_evidence_error(error: Exception) -> bool:
    """Limit retries to transient infrastructure and policy-verification errors."""

    return isinstance(
        error,
        (
            ConnectionError,
            TimeoutError,
            psycopg.OperationalError,
            PolicyVerificationError,
            TransientEvidenceError,
        ),
    )


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _money(value: Decimal | int | str) -> str:
    return f"{Decimal(value):.2f}"


def _order_number(state: ReturnWorkflowState) -> str:
    explicit = state.get("order_number", "").strip().upper()
    if explicit:
        return explicit
    match = ORDER_NUMBER_PATTERN.search(state["customer_message"])
    if match is None:
        raise ValueError(
            "No order_number was supplied and none could be read from the request"
        )
    return match.group(0).upper()


def create_order_lookup_node(
    connection_url: str,
) -> Callable[[ReturnWorkflowState], dict[str, OrderLookupResult]]:
    """Create a node that validates order ownership and returns item snapshots."""

    def lookup_order(
        state: ReturnWorkflowState,
    ) -> dict[str, OrderLookupResult]:
        order_number = _order_number(state)
        customer_id = state["customer_id"].strip()
        if not customer_id:
            raise ValueError("customer_id must not be empty")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                ORDER_LOOKUP_SQL,
                (customer_id, order_number),
            ).fetchall()

        if not rows:
            return {
                "order_lookup": {
                    "found": False,
                    "customer_match": False,
                    "order_number": order_number,
                    "order_id": None,
                    "order_status": None,
                    "currency": None,
                    "ordered_at": None,
                    "days_since_order": None,
                    "refundable_item_total": None,
                    "shipping_amount": None,
                    "items": [],
                }
            }

        ordered_at = rows[0]["ordered_at"]
        now = datetime.now(timezone.utc)
        days_since_order = max(0, (now - ordered_at).days)
        items: list[OrderItemEvidence] = []
        refundable_total = Decimal("0")
        for row in rows:
            refundable_total += row["line_total"]
            items.append(
                {
                    "order_item_id": str(row["order_item_id"]),
                    "sku": row["sku"],
                    "product_name": row["product_name"],
                    "product_category": row["product_category"],
                    "quantity": int(row["quantity"]),
                    "unit_price": _money(row["unit_price"]),
                    "tax_amount": _money(row["tax_amount"]),
                    "line_total": _money(row["line_total"]),
                    "activated_at": _iso(row["activated_at"]),
                }
            )

        result: OrderLookupResult = {
            "found": True,
            "customer_match": True,
            "order_number": rows[0]["order_number"],
            "order_id": str(rows[0]["order_id"]),
            "order_status": rows[0]["order_status"],
            "currency": rows[0]["currency"],
            "ordered_at": _iso(ordered_at),
            "days_since_order": days_since_order,
            "refundable_item_total": _money(refundable_total),
            "shipping_amount": _money(rows[0]["shipping_amount"]),
            "items": items,
        }
        return {"order_lookup": result}

    return lookup_order


def create_policy_retrieval_node(
    connection_url: str,
    vector_store: CockroachDBVectorStore,
    namespace: str,
    embedding_model: str,
    embedding_dimensions: int,
    *,
    result_count: int = 8,
) -> Callable[[ReturnWorkflowState], dict[str, PolicyEvidenceResult]]:
    """Create a semantic retrieval node with relational citation verification."""

    try:
        policy_key, policy_version = namespace.rsplit(":", 1)
    except ValueError as error:
        raise ValueError("Policy namespace must end with ':<version>'") from error

    def retrieve_policy(
        state: ReturnWorkflowState,
    ) -> dict[str, PolicyEvidenceResult]:
        query = state["customer_message"].strip()
        if not query:
            raise ValueError("customer_message must not be empty")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                AUTHORITATIVE_POLICY_SQL,
                (policy_key, policy_version),
            ).fetchall()
        authoritative = {row["clause_key"]: row for row in rows}
        if not authoritative:
            raise PolicyVerificationError(
                "No active authoritative clauses exist for the configured policy"
            )

        retrieved = vector_store.similarity_search_with_score(
            query,
            k=result_count,
        )
        if not retrieved:
            raise PolicyVerificationError("Semantic search returned no policy clauses")

        citations: list[PolicyCitation] = []
        for document, score in retrieved:
            metadata: dict[str, Any] = document.metadata
            if not REQUIRED_POLICY_METADATA.issubset(metadata):
                raise PolicyVerificationError(
                    "Retrieved policy chunk is missing required citation metadata"
                )
            clause_key = str(metadata["clause_key"])
            clause = authoritative.get(clause_key)
            if clause is None:
                raise PolicyVerificationError(
                    f"Retrieved clause {clause_key!r} is not authoritative"
                )

            checks = (
                (str(metadata["return_policy_id"]), str(clause["return_policy_id"])),
                (str(metadata["policy_clause_id"]), str(clause["policy_clause_id"])),
                (metadata["document_title"], clause["title"]),
                (metadata["policy_key"], clause["policy_key"]),
                (metadata["policy_version"], clause["policy_version"]),
                (metadata["source_uri"], clause["source_uri"]),
                (metadata["content_sha256"], clause["content_sha256"]),
                (metadata["embedding_model"], embedding_model),
                (int(metadata["embedding_dimensions"]), embedding_dimensions),
                (
                    _normalized_text(document.page_content),
                    _normalized_text(clause["clause_text"]),
                ),
            )
            if any(actual != expected for actual, expected in checks):
                raise PolicyVerificationError(
                    f"Retrieved clause {clause_key!r} failed source verification"
                )

            citations.append(
                {
                    "document_title": str(metadata["document_title"]),
                    "policy_key": str(metadata["policy_key"]),
                    "policy_version": str(metadata["policy_version"]),
                    "section_heading": str(metadata["section_heading"]),
                    "clause_key": clause_key,
                    "source_uri": str(metadata["source_uri"]),
                    "content_sha256": str(metadata["content_sha256"]),
                    "quote": _normalized_text(document.page_content),
                    "distance_score": float(score),
                }
            )

        return {
            "policy_evidence": {
                "verified": True,
                "query": query,
                "namespace": namespace,
                "citations": citations,
            }
        }

    return retrieve_policy


def create_fraud_assessment_node(
    connection_url: str,
) -> Callable[[ReturnWorkflowState], dict[str, FraudAssessmentResult]]:
    """Create a deterministic, explainable demo fraud-signal assessment node."""

    def assess_fraud(
        state: ReturnWorkflowState,
    ) -> dict[str, FraudAssessmentResult]:
        customer_id = state["customer_id"].strip()
        if not customer_id:
            raise ValueError("customer_id must not be empty")

        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            row = connection.execute(
                FRAUD_ASSESSMENT_SQL,
                (customer_id,),
            ).fetchone()

        if row is None:
            return {
                "fraud_assessment": {
                    "customer_found": False,
                    "account_status": None,
                    "prior_refunded_requests": 0,
                    "prior_refunded_amount": "0.00",
                    "risk_score": 100,
                    "risk_level": "unknown",
                    "requires_manual_review": True,
                    "signal_codes": ["CUSTOMER_NOT_FOUND"],
                    "assessment_basis": "demo_rules_v1",
                }
            }

        account_status = row["account_status"]
        prior_count = int(row["prior_refunded_requests"])
        prior_amount = Decimal(row["prior_refunded_amount"])
        score = 0
        signals: list[str] = []

        if account_status == "restricted":
            score += 60
            signals.append("ACCOUNT_RESTRICTED")
        elif account_status == "closed":
            score += 80
            signals.append("ACCOUNT_CLOSED")
        if prior_count >= 3:
            score += 30
            signals.append("THREE_OR_MORE_PRIOR_REFUNDS")
        if prior_amount >= Decimal("500.00"):
            score += 20
            signals.append("PRIOR_REFUNDS_AT_LEAST_500")

        score = min(score, 100)
        risk_level = "high" if score >= 70 else "medium" if score >= 30 else "low"
        result: FraudAssessmentResult = {
            "customer_found": True,
            "account_status": account_status,
            "prior_refunded_requests": prior_count,
            "prior_refunded_amount": _money(prior_amount),
            "risk_score": score,
            "risk_level": risk_level,
            "requires_manual_review": score >= 50,
            "signal_codes": signals,
            "assessment_basis": "demo_rules_v1",
        }
        return {"fraud_assessment": result}

    return assess_fraud
