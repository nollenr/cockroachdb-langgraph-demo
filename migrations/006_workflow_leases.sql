-- Product Returns demo: renewable run leases and stale-worker fencing.
--
-- lease_generation is a per-run counter, not a global sequence or key. It is
-- incremented only when a worker claims or reclaims a run. Every durable state
-- transition made by a worker must be conditional on the generation it owns.

USE product_returns;

ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS graph_version STRING NULL,
    ADD COLUMN IF NOT EXISTS lease_owner STRING NULL,
    ADD COLUMN IF NOT EXISTS lease_generation INT8 NOT NULL DEFAULT 0
        CHECK (lease_generation >= 0),
    ADD COLUMN IF NOT EXISTS lease_acquired_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS last_heartbeat_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ NULL;

-- Existing runs predate explicit graph versioning and therefore belong to
-- version 1. This is a one-time upgrade backfill, not a column default.
UPDATE workflow_runs
SET graph_version = '1'
WHERE graph_version IS NULL;

-- New runs must explicitly supply the version declared by the Python graph.
-- With no DEFAULT, omission fails instead of silently labeling new code as v1.
ALTER TABLE workflow_runs
    ALTER COLUMN graph_version SET NOT NULL;

ALTER TABLE workflow_runs
    ADD CONSTRAINT IF NOT EXISTS workflow_runs_graph_version_nonempty CHECK (
        length(trim(graph_version)) > 0
    );

-- A running row must have one complete lease; every non-running row must have
-- no active lease. lease_generation is intentionally retained after release.
ALTER TABLE workflow_runs
    ADD CONSTRAINT IF NOT EXISTS workflow_runs_lease_completeness CHECK (
        (
            run_status = 'running'
            AND lease_owner IS NOT NULL
            AND lease_acquired_at IS NOT NULL
            AND last_heartbeat_at IS NOT NULL
            AND lease_expires_at IS NOT NULL
        )
        OR
        (
            run_status <> 'running'
            AND lease_owner IS NULL
            AND lease_acquired_at IS NULL
            AND last_heartbeat_at IS NULL
            AND lease_expires_at IS NULL
        )
    );

ALTER TABLE workflow_runs
    ADD CONSTRAINT IF NOT EXISTS workflow_runs_lease_time_order CHECK (
        lease_acquired_at IS NULL
        OR (
            last_heartbeat_at >= lease_acquired_at
            AND lease_expires_at > last_heartbeat_at
        )
    );

-- This is the scheduler's access path for finding abandoned running work.
-- lease_generation is deliberately not indexed.
CREATE INDEX IF NOT EXISTS workflow_runs_by_expired_lease
    ON workflow_runs (lease_expires_at)
    STORING (
        run_id,
        thread_id,
        return_request_id,
        lease_owner,
        lease_generation,
        latest_checkpoint_id,
        state_version,
        graph_version
    )
    WHERE run_status = 'running';

SHOW COLUMNS FROM workflow_runs;
SHOW CONSTRAINTS FROM workflow_runs;
SHOW INDEXES FROM workflow_runs;
