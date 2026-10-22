-- Product Returns demo: durable workflow, human approval, refund, and audit data.
--
-- LangGraph's CockroachDBSaver owns its checkpoint tables. Its setup() method
-- should be run once during deployment as ron. Do not reproduce those internal
-- tables here or couple application code to their implementation details.

USE product_returns;

CREATE TABLE IF NOT EXISTS workflow_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    return_request_id UUID NOT NULL UNIQUE
        REFERENCES return_requests (return_request_id),
    thread_id STRING NOT NULL UNIQUE,
    run_status STRING NOT NULL DEFAULT 'ready'
        CHECK (run_status IN (
            'ready',
            'running',
            'retry_wait',
            'waiting_for_approval',
            'completed',
            'rejected',
            'failed'
        )),
    current_round STRING NOT NULL DEFAULT 'classification',
    next_nodes STRING[] NOT NULL DEFAULT ARRAY[]::STRING[],
    latest_checkpoint_id STRING NULL,
    state_version INT8 NOT NULL DEFAULT 0 CHECK (state_version >= 0),
    next_attempt_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    INDEX workflow_runs_by_status_time (run_status, next_attempt_at, updated_at)
        STORING (thread_id, return_request_id, current_round, next_nodes)
);

CREATE TABLE IF NOT EXISTS node_attempts (
    node_attempt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES workflow_runs (run_id),
    node_name STRING NOT NULL,
    attempt_number INT8 NOT NULL CHECK (attempt_number > 0),
    attempt_status STRING NOT NULL
        CHECK (attempt_status IN ('started', 'succeeded', 'retryable_failure', 'failed')),
    input_checkpoint_id STRING NULL,
    output_checkpoint_id STRING NULL,
    output_summary JSONB NULL,
    error_code STRING NULL,
    error_message STRING NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NULL,
    UNIQUE (run_id, node_name, attempt_number),
    INDEX node_attempts_by_run (run_id, started_at)
        STORING (node_name, attempt_number, attempt_status, finished_at),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS approval_requests (
    approval_request_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES workflow_runs (run_id),
    request_number INT8 NOT NULL DEFAULT 1 CHECK (request_number > 0),
    approval_status STRING NOT NULL DEFAULT 'pending'
        CHECK (approval_status IN ('pending', 'approved', 'rejected', 'cancelled')),
    refund_amount DECIMAL(18, 2) NOT NULL CHECK (refund_amount >= 0),
    currency STRING(3) NOT NULL,
    approval_reason STRING NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at TIMESTAMPTZ NULL,
    decided_by STRING NULL,
    decision_note STRING NULL,
    UNIQUE (run_id, request_number),
    UNIQUE INDEX one_pending_approval_per_run (run_id)
        WHERE approval_status = 'pending',
    INDEX approval_queue (approval_status, requested_at)
        STORING (run_id, refund_amount, currency, approval_reason),
    CHECK (decided_at IS NULL OR decided_at >= requested_at),
    CHECK (
        (approval_status = 'pending' AND decided_at IS NULL AND decided_by IS NULL)
        OR
        (approval_status <> 'pending' AND decided_at IS NOT NULL AND decided_by IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL UNIQUE REFERENCES workflow_runs (run_id),
    return_request_id UUID NOT NULL UNIQUE
        REFERENCES return_requests (return_request_id),
    idempotency_key STRING NOT NULL UNIQUE,
    refund_status STRING NOT NULL DEFAULT 'pending'
        CHECK (refund_status IN ('pending', 'processing', 'succeeded', 'failed')),
    refund_amount DECIMAL(18, 2) NOT NULL CHECK (refund_amount >= 0),
    currency STRING(3) NOT NULL,
    payment_provider STRING NOT NULL,
    provider_refund_id STRING NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    UNIQUE (payment_provider, provider_refund_id),
    CHECK (completed_at IS NULL OR completed_at >= created_at)
);

CREATE TABLE IF NOT EXISTS refund_attempts (
    refund_attempt_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    refund_id UUID NOT NULL REFERENCES refunds (refund_id),
    attempt_number INT8 NOT NULL CHECK (attempt_number > 0),
    attempt_status STRING NOT NULL
        CHECK (attempt_status IN ('started', 'succeeded', 'retryable_failure', 'failed')),
    provider_request_id STRING NULL,
    provider_response JSONB NULL,
    error_code STRING NULL,
    error_message STRING NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ NULL,
    UNIQUE (refund_id, attempt_number),
    UNIQUE (provider_request_id),
    INDEX refund_attempts_by_refund (refund_id, started_at)
        STORING (attempt_number, attempt_status, finished_at),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES workflow_runs (run_id),
    sequence_number INT8 NOT NULL CHECK (sequence_number > 0),
    event_type STRING NOT NULL,
    node_name STRING NULL,
    actor_type STRING NOT NULL
        CHECK (actor_type IN ('system', 'customer', 'manager', 'payment_provider')),
    actor_id STRING NULL,
    checkpoint_id STRING NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::JSONB,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, sequence_number),
    INDEX audit_events_by_run_time (run_id, occurred_at)
        STORING (sequence_number, event_type, node_name, actor_type, checkpoint_id)
);

-- The application should treat audit_events as append-only. A later hardening
-- migration can revoke UPDATE and DELETE after we separate runtime roles for
-- workflow execution and administrative maintenance.
