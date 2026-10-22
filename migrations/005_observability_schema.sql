-- Product Returns demo: durable correlation fields for graph observability.
--
-- Prometheus intentionally receives only bounded labels such as node and
-- outcome. Per-run identifiers and full JSON state belong in traces, logs, and
-- these durable workflow records.

USE product_returns;

ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS initial_trace_id STRING NULL
        CHECK (initial_trace_id IS NULL OR length(initial_trace_id) = 32);

ALTER TABLE node_attempts
    ADD COLUMN IF NOT EXISTS trace_id STRING NULL
        CHECK (trace_id IS NULL OR length(trace_id) = 32),
    ADD COLUMN IF NOT EXISTS span_id STRING NULL
        CHECK (span_id IS NULL OR length(span_id) = 16),
    ADD COLUMN IF NOT EXISTS input_state JSONB NULL
        CHECK (input_state IS NULL OR jsonb_typeof(input_state) = 'object'),
    ADD COLUMN IF NOT EXISTS output_state_delta JSONB NULL
        CHECK (
            output_state_delta IS NULL
            OR jsonb_typeof(output_state_delta) = 'object'
        ),
    ADD COLUMN IF NOT EXISTS output_state JSONB NULL
        CHECK (output_state IS NULL OR jsonb_typeof(output_state) = 'object');

CREATE INDEX IF NOT EXISTS node_attempts_by_trace
    ON node_attempts (trace_id, started_at)
    STORING (
        run_id,
        span_id,
        node_name,
        attempt_number,
        attempt_status,
        finished_at
    )
    WHERE trace_id IS NOT NULL;

ALTER TABLE audit_events
    ADD COLUMN IF NOT EXISTS trace_id STRING NULL
        CHECK (trace_id IS NULL OR length(trace_id) = 32),
    ADD COLUMN IF NOT EXISTS span_id STRING NULL
        CHECK (span_id IS NULL OR length(span_id) = 16);

CREATE INDEX IF NOT EXISTS audit_events_by_trace
    ON audit_events (trace_id, occurred_at)
    STORING (
        run_id,
        span_id,
        sequence_number,
        event_type,
        node_name,
        actor_type,
        checkpoint_id
    )
    WHERE trace_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS workflow_runs_by_created
    ON workflow_runs (created_at DESC)
    STORING (
        thread_id,
        run_status,
        current_round,
        next_nodes,
        initial_trace_id,
        updated_at
    );

SELECT
    table_name,
    column_name,
    data_type,
    is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('workflow_runs', 'node_attempts', 'audit_events')
  AND column_name IN (
      'initial_trace_id',
      'trace_id',
      'span_id',
      'input_state',
      'output_state_delta',
      'output_state'
  )
ORDER BY table_name, ordinal_position;

SHOW INDEXES FROM node_attempts;
SHOW INDEXES FROM audit_events;
SHOW INDEXES FROM workflow_runs;

