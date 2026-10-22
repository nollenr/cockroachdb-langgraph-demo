-- Product Returns demo: deterministic, one-shot resilience demonstrations.
--
-- Failure injection is intentionally isolated from customer/business state.
-- One row can request one synthetic node failure for one synthetic workflow.

USE product_returns;

CREATE TABLE IF NOT EXISTS workflow_failure_injections (
    run_id UUID PRIMARY KEY REFERENCES workflow_runs (run_id),
    node_name STRING NOT NULL
        CHECK (node_name IN ('lookup_order', 'retrieve_policy', 'assess_fraud')),
    failure_mode STRING NOT NULL DEFAULT 'fail_once_before_node'
        CHECK (failure_mode = 'fail_once_before_node'),
    injection_status STRING NOT NULL DEFAULT 'planned'
        CHECK (injection_status IN ('planned', 'triggered', 'resumed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    triggered_at TIMESTAMPTZ NULL,
    resumed_at TIMESTAMPTZ NULL,
    CHECK (
        (injection_status = 'planned'
            AND triggered_at IS NULL AND resumed_at IS NULL)
        OR
        (injection_status = 'triggered'
            AND triggered_at IS NOT NULL AND resumed_at IS NULL)
        OR
        (injection_status = 'resumed'
            AND triggered_at IS NOT NULL AND resumed_at IS NOT NULL)
    )
) LOCALITY REGIONAL BY TABLE IN PRIMARY REGION;

SELECT count(*) AS workflow_failure_injection_count
FROM workflow_failure_injections;
