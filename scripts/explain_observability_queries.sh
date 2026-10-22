#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN
SELECT
    run_id,
    thread_id,
    run_status,
    current_round,
    next_nodes,
    initial_trace_id,
    created_at,
    updated_at
FROM workflow_runs
ORDER BY created_at DESC
LIMIT 20;

EXPLAIN
SELECT
    node_attempt_id,
    node_name,
    attempt_number,
    attempt_status,
    trace_id,
    span_id,
    input_state,
    output_state_delta,
    output_state,
    error_code,
    error_message,
    started_at,
    finished_at
FROM node_attempts
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
ORDER BY started_at;

EXPLAIN
SELECT
    run_id,
    node_name,
    attempt_number,
    attempt_status,
    span_id,
    started_at,
    finished_at
FROM node_attempts
WHERE trace_id = '00000000000000000000000000000000'
ORDER BY started_at;

EXPLAIN
SELECT
    sequence_number,
    event_type,
    node_name,
    actor_type,
    trace_id,
    span_id,
    checkpoint_id,
    event_data,
    occurred_at
FROM audit_events
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
ORDER BY occurred_at;
SQL
