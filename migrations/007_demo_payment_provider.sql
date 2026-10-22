-- Product Returns demo: external payment-provider idempotency simulation.
--
-- This table intentionally represents state owned by the demo provider, not
-- LangGraph state. A unique idempotency key guarantees that repeated requests
-- return the original provider refund instead of issuing another refund.

USE product_returns;

CREATE TABLE IF NOT EXISTS demo_payment_provider_refunds (
    provider_refund_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    idempotency_key STRING NOT NULL UNIQUE,
    run_id UUID NOT NULL,
    refund_amount DECIMAL(18, 2) NOT NULL CHECK (refund_amount >= 0),
    currency STRING(3) NOT NULL,
    provider_status STRING NOT NULL DEFAULT 'succeeded'
        CHECK (provider_status = 'succeeded'),
    request_count INT8 NOT NULL DEFAULT 1 CHECK (request_count > 0),
    first_requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX demo_provider_by_run (run_id)
        STORING (
            provider_refund_id,
            idempotency_key,
            refund_amount,
            currency,
            provider_status,
            request_count,
            last_requested_at
        ),
    CHECK (last_requested_at >= first_requested_at)
);

-- Default privileges created by migration 001 grant future ron-owned tables to
-- product_returns_app. Rerun migration 001 after this migration to verify them.
