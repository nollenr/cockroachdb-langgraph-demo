-- Product Returns demo: commerce and returns domain schema.
--
-- Run this migration as the object owner (ron), not as product_returns_app.
-- Each statement is intentionally left in its own implicit transaction so that
-- CockroachDB can execute schema changes independently.

USE product_returns;

CREATE TABLE IF NOT EXISTS customers (
    customer_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_customer_id STRING NOT NULL UNIQUE,
    email STRING NOT NULL,
    account_status STRING NOT NULL DEFAULT 'active'
        CHECK (account_status IN ('active', 'restricted', 'closed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS products (
    product_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sku STRING NOT NULL UNIQUE,
    product_name STRING NOT NULL,
    product_category STRING NOT NULL,
    is_active BOOL NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    order_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_number STRING NOT NULL UNIQUE,
    customer_id UUID NOT NULL REFERENCES customers (customer_id),
    order_status STRING NOT NULL
        CHECK (order_status IN ('placed', 'paid', 'shipped', 'delivered', 'cancelled')),
    currency STRING(3) NOT NULL,
    subtotal_amount DECIMAL(18, 2) NOT NULL CHECK (subtotal_amount >= 0),
    tax_amount DECIMAL(18, 2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    shipping_amount DECIMAL(18, 2) NOT NULL DEFAULT 0 CHECK (shipping_amount >= 0),
    total_amount DECIMAL(18, 2) NOT NULL CHECK (total_amount >= 0),
    ordered_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX orders_by_customer_time (customer_id, ordered_at DESC)
        STORING (order_number, order_status, currency, total_amount)
);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id UUID NOT NULL REFERENCES orders (order_id),
    product_id UUID NOT NULL REFERENCES products (product_id),
    sku STRING NOT NULL,
    product_name STRING NOT NULL,
    product_category STRING NOT NULL,
    quantity INT8 NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(18, 2) NOT NULL CHECK (unit_price >= 0),
    tax_amount DECIMAL(18, 2) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
    line_total DECIMAL(18, 2) NOT NULL CHECK (line_total >= 0),
    activated_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX order_items_by_order (order_id)
        STORING (
            product_id,
            sku,
            product_name,
            product_category,
            quantity,
            unit_price,
            line_total,
            activated_at
        )
);

CREATE TABLE IF NOT EXISTS return_policies (
    return_policy_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_key STRING NOT NULL,
    policy_version STRING NOT NULL,
    title STRING NOT NULL,
    policy_status STRING NOT NULL DEFAULT 'draft'
        CHECK (policy_status IN ('draft', 'active', 'retired')),
    effective_from TIMESTAMPTZ NOT NULL,
    effective_until TIMESTAMPTZ NULL,
    source_uri STRING NULL,
    content_sha256 STRING NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (policy_key, policy_version),
    CHECK (effective_until IS NULL OR effective_until > effective_from),
    INDEX active_return_policies (policy_key, effective_from DESC)
        STORING (policy_version, title, effective_until, content_sha256)
        WHERE policy_status = 'active'
);

CREATE TABLE IF NOT EXISTS policy_clauses (
    policy_clause_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    return_policy_id UUID NOT NULL REFERENCES return_policies (return_policy_id),
    clause_key STRING NOT NULL,
    clause_text STRING NOT NULL,
    display_order INT8 NOT NULL CHECK (display_order >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (return_policy_id, clause_key),
    UNIQUE (return_policy_id, display_order)
);

-- Derived semantic-search index for the authoritative return-policy document.
-- The column names match CockroachDBVectorStore's defaults. Citation and
-- verification fields (title, policy/version, section heading, clause key,
-- source URI/hash, and chunk index) are stored in metadata JSONB and validated
-- by the ingestion application before each write.
CREATE TABLE IF NOT EXISTS policy_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    namespace STRING NOT NULL CHECK (length(namespace) > 0),
    content STRING NOT NULL CHECK (length(content) > 0),
    embedding VECTOR(1536) NOT NULL,
    metadata JSONB NOT NULL
        CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX policy_chunks_namespace_idx (namespace)
);

CREATE TABLE IF NOT EXISTS return_requests (
    return_request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers (customer_id),
    order_id UUID NULL REFERENCES orders (order_id),
    request_text STRING NOT NULL,
    classified_intent STRING NOT NULL DEFAULT 'unclassified'
        CHECK (classified_intent IN ('unclassified', 'refund', 'complaint', 'other')),
    request_status STRING NOT NULL DEFAULT 'received'
        CHECK (request_status IN (
            'received',
            'classifying',
            'gathering_evidence',
            'pending_approval',
            'approved',
            'rejected',
            'refunding',
            'refunded',
            'failed'
        )),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX return_requests_by_customer_time (customer_id, requested_at DESC)
        STORING (order_id, classified_intent, request_status),
    INDEX return_requests_by_order (order_id, requested_at DESC)
        STORING (customer_id, classified_intent, request_status)
);

CREATE TABLE IF NOT EXISTS return_items (
    return_item_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    return_request_id UUID NOT NULL REFERENCES return_requests (return_request_id),
    order_item_id UUID NOT NULL REFERENCES order_items (order_item_id),
    requested_quantity INT8 NOT NULL CHECK (requested_quantity > 0),
    return_reason STRING NULL,
    requested_refund_amount DECIMAL(18, 2) NOT NULL CHECK (requested_refund_amount >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (return_request_id, order_item_id),
    INDEX return_items_by_request (return_request_id)
        STORING (order_item_id, requested_quantity, requested_refund_amount)
);

-- Default privileges from 001_runtime_privileges.sql cover these tables when
-- they are created by ron. Rerun that migration's verification queries after
-- this migration to confirm the effective grants.
