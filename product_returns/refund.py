"""Idempotent refund execution with an external-provider simulation."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from time import sleep
from typing import Any, cast
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from product_returns.state import RefundResult, ReturnWorkflowState


PAYMENT_PROVIDER = "demo_payment_provider"


class TransientRefundError(RuntimeError):
    """A retryable failure after the provider may already have acted."""


@dataclass(frozen=True)
class PreparedRefund:
    refund_id: UUID
    refund_attempt_id: UUID | None
    attempt_number: int | None
    run_id: UUID
    return_request_id: UUID
    idempotency_key: str
    refund_amount: Decimal
    currency: str
    completed_result: RefundResult | None = None


@dataclass(frozen=True)
class ProviderRefund:
    provider_refund_id: UUID
    provider_request_count: int
    provider_status: str


def _retry_delay(attempt: int) -> None:
    base_delay = min(0.05 * (2**attempt), 0.8)
    sleep(base_delay + random.uniform(0, base_delay))


def refund_idempotency_key(run_id: UUID) -> str:
    """Return the stable identity used for every provider retry of this run."""

    return f"product-returns:{run_id}:refund:v1"


def _refund_terms(state: ReturnWorkflowState) -> tuple[UUID, Decimal, str]:
    reservation = state.get("return_reservation")
    if reservation is None or reservation["status"] != "reserved":
        raise ValueError("Refund node requires a successful item-quantity reservation")
    decision = state.get("decision")
    if decision is None or not decision["eligible"]:
        raise ValueError("Refund node requires an eligible return decision")
    if decision["requires_manager_approval"]:
        manager = state.get("manager_decision")
        if manager is None or manager["decision"] != "approved":
            raise ValueError("Refund node requires recorded manager approval")
    amount_text = decision["approved_refund_amount"] or decision["calculated_refund_amount"]
    currency = decision["currency"]
    if not currency:
        raise ValueError("Refund decision has no currency")
    amount = Decimal(amount_text).quantize(Decimal("0.01"))
    if amount <= 0:
        raise ValueError("Refund amount must be greater than zero")
    return UUID(state["run_id"]), amount, currency


def _completed_result(
    connection: psycopg.Connection[dict[str, Any]],
    row: dict[str, Any],
) -> RefundResult:
    provider = connection.execute(
        """
        SELECT request_count
        FROM demo_payment_provider_refunds
        WHERE idempotency_key = %s
        """,
        (row["idempotency_key"],),
    ).fetchone()
    if provider is None:
        raise RuntimeError("Succeeded local refund has no provider record")
    return {
        "refund_id": str(row["refund_id"]),
        "idempotency_key": row["idempotency_key"],
        "payment_provider": PAYMENT_PROVIDER,
        "provider_refund_id": str(row["provider_refund_id"]),
        "refund_amount": f"{row['refund_amount']:.2f}",
        "currency": row["currency"],
        "refund_status": "succeeded",
        "provider_request_count": int(provider["request_count"]),
    }


def prepare_refund_attempt(
    connection_url: str,
    state: ReturnWorkflowState,
    *,
    max_attempts: int = 5,
) -> PreparedRefund:
    """Create/reuse the logical refund and start one auditable attempt."""

    run_id, amount, currency = _refund_terms(state)
    key = refund_idempotency_key(run_id)
    for transaction_attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    refund = connection.execute(
                        """
                        INSERT INTO refunds (
                            run_id, return_request_id, idempotency_key,
                            refund_status, refund_amount, currency, payment_provider
                        )
                        SELECT
                            run_id, return_request_id, %s,
                            'processing', %s, %s, %s
                        FROM workflow_runs
                        WHERE run_id = %s
                          AND run_status = 'running'
                        ON CONFLICT (run_id) DO UPDATE SET
                            refund_status = CASE
                                WHEN refunds.refund_status = 'succeeded'
                                    THEN 'succeeded'
                                ELSE 'processing'
                            END,
                            updated_at = now()
                        WHERE refunds.idempotency_key = excluded.idempotency_key
                          AND refunds.refund_amount = excluded.refund_amount
                          AND refunds.currency = excluded.currency
                          AND refunds.payment_provider = excluded.payment_provider
                        RETURNING
                            refund_id, return_request_id, idempotency_key,
                            refund_status, refund_amount, currency,
                            provider_refund_id
                        """,
                        (key, amount, currency, PAYMENT_PROVIDER, run_id),
                    ).fetchone()
                    if refund is None:
                        raise RuntimeError(
                            "Refund run is not active or its immutable refund terms changed"
                        )
                    refund_id = cast(UUID, refund["refund_id"])
                    return_request_id = cast(UUID, refund["return_request_id"])
                    if refund["refund_status"] == "succeeded":
                        result = _completed_result(connection, refund)
                        return PreparedRefund(
                            refund_id=refund_id,
                            refund_attempt_id=None,
                            attempt_number=None,
                            run_id=run_id,
                            return_request_id=return_request_id,
                            idempotency_key=key,
                            refund_amount=amount,
                            currency=currency,
                            completed_result=result,
                        )

                    connection.execute(
                        """
                        UPDATE refund_attempts
                        SET
                            attempt_status = 'retryable_failure',
                            error_code = 'WORKER_INTERRUPTED',
                            error_message = 'A later attempt reclaimed this unfinished refund.',
                            finished_at = now()
                        WHERE refund_id = %s
                          AND attempt_status = 'started'
                        RETURNING NOTHING
                        """,
                        (refund_id,),
                    )
                    next_attempt = connection.execute(
                        """
                        SELECT COALESCE(max(attempt_number), 0) + 1 AS attempt_number
                        FROM refund_attempts
                        WHERE refund_id = %s
                        """,
                        (refund_id,),
                    ).fetchone()
                    if next_attempt is None:
                        raise RuntimeError("Could not allocate a refund attempt number")
                    attempt_number = int(next_attempt["attempt_number"])
                    attempt = connection.execute(
                        """
                        INSERT INTO refund_attempts (
                            refund_id, attempt_number, attempt_status,
                            provider_request_id
                        ) VALUES (%s, %s, 'started', %s)
                        RETURNING refund_attempt_id
                        """,
                        (refund_id, attempt_number, f"{key}:attempt:{attempt_number}"),
                    ).fetchone()
                    if attempt is None:
                        raise RuntimeError("Could not create refund attempt")

                return PreparedRefund(
                    refund_id=refund_id,
                    refund_attempt_id=cast(UUID, attempt["refund_attempt_id"]),
                    attempt_number=attempt_number,
                    run_id=run_id,
                    return_request_id=return_request_id,
                    idempotency_key=key,
                    refund_amount=amount,
                    currency=currency,
                )
        except psycopg.errors.SerializationFailure:
            if transaction_attempt + 1 >= max_attempts:
                raise
            _retry_delay(transaction_attempt)
    raise AssertionError("Unreachable transaction retry state")


def request_provider_refund(
    connection_url: str,
    prepared: PreparedRefund,
) -> ProviderRefund:
    """Ask the simulated provider; duplicate keys return the original refund."""

    with psycopg.connect(connection_url, row_factory=dict_row, autocommit=True) as connection:
        row = connection.execute(
            """
            INSERT INTO demo_payment_provider_refunds (
                idempotency_key, run_id, refund_amount, currency, provider_status
            ) VALUES (%s, %s, %s, %s, 'succeeded')
            ON CONFLICT (idempotency_key) DO UPDATE SET
                request_count = demo_payment_provider_refunds.request_count + 1,
                last_requested_at = now()
            WHERE demo_payment_provider_refunds.run_id = excluded.run_id
              AND demo_payment_provider_refunds.refund_amount = excluded.refund_amount
              AND demo_payment_provider_refunds.currency = excluded.currency
            RETURNING provider_refund_id, request_count, provider_status
            """,
            (
                prepared.idempotency_key,
                prepared.run_id,
                prepared.refund_amount,
                prepared.currency,
            ),
        ).fetchone()
    if row is None:
        raise RuntimeError("Provider rejected a reused idempotency key with different terms")
    return ProviderRefund(
        provider_refund_id=cast(UUID, row["provider_refund_id"]),
        provider_request_count=int(row["request_count"]),
        provider_status=cast(str, row["provider_status"]),
    )


def complete_refund_attempt(
    connection_url: str,
    prepared: PreparedRefund,
    provider: ProviderRefund,
    *,
    max_attempts: int = 5,
) -> RefundResult:
    """Record provider success locally in a short retryable transaction."""

    if prepared.refund_attempt_id is None:
        raise ValueError("A completed refund has no open attempt to finish")
    for transaction_attempt in range(max_attempts):
        try:
            with psycopg.connect(connection_url, row_factory=dict_row) as connection:
                with connection.transaction():
                    refund = connection.execute(
                        """
                        UPDATE refunds
                        SET
                            refund_status = 'succeeded',
                            provider_refund_id = %s,
                            completed_at = COALESCE(completed_at, now()),
                            updated_at = now()
                        WHERE refund_id = %s
                          AND idempotency_key = %s
                          AND refund_status IN ('processing', 'succeeded')
                          AND (provider_refund_id IS NULL OR provider_refund_id = %s)
                        RETURNING refund_id
                        """,
                        (
                            str(provider.provider_refund_id),
                            prepared.refund_id,
                            prepared.idempotency_key,
                            str(provider.provider_refund_id),
                        ),
                    ).fetchone()
                    if refund is None:
                        raise RuntimeError("Local refund no longer matches provider success")
                    finished = connection.execute(
                        """
                        UPDATE refund_attempts
                        SET
                            attempt_status = 'succeeded',
                            provider_response = %s,
                            finished_at = now()
                        WHERE refund_attempt_id = %s
                          AND attempt_status = 'started'
                        RETURNING refund_attempt_id
                        """,
                        (
                            Jsonb(
                                {
                                    "provider_refund_id": str(provider.provider_refund_id),
                                    "provider_status": provider.provider_status,
                                    "provider_request_count": provider.provider_request_count,
                                }
                            ),
                            prepared.refund_attempt_id,
                        ),
                    ).fetchone()
                    if finished is None:
                        raise RuntimeError("Refund attempt was no longer open")
                return {
                    "refund_id": str(prepared.refund_id),
                    "idempotency_key": prepared.idempotency_key,
                    "payment_provider": PAYMENT_PROVIDER,
                    "provider_refund_id": str(provider.provider_refund_id),
                    "refund_amount": f"{prepared.refund_amount:.2f}",
                    "currency": prepared.currency,
                    "refund_status": "succeeded",
                    "provider_request_count": provider.provider_request_count,
                }
        except psycopg.errors.SerializationFailure:
            if transaction_attempt + 1 >= max_attempts:
                raise
            _retry_delay(transaction_attempt)
    raise AssertionError("Unreachable transaction retry state")


def create_issue_refund_node(
    connection_url: str,
    *,
    after_provider_hook: Callable[[PreparedRefund, ProviderRefund], None] | None = None,
) -> Callable[[ReturnWorkflowState], dict[str, RefundResult]]:
    """Build the final node; the optional hook supports the crash-window test."""

    def issue_refund(state: ReturnWorkflowState) -> dict[str, RefundResult]:
        prepared = prepare_refund_attempt(connection_url, state)
        if prepared.completed_result is not None:
            return {"refund_result": prepared.completed_result}
        provider = request_provider_refund(connection_url, prepared)
        if after_provider_hook is not None:
            after_provider_hook(prepared, provider)
        result = complete_refund_attempt(connection_url, prepared, provider)
        return {"refund_result": result}

    return issue_refund


def retryable_refund_error(error: Exception) -> bool:
    """Restrict LangGraph retries to explicitly transient refund failures."""

    return isinstance(error, (TransientRefundError, psycopg.OperationalError))
