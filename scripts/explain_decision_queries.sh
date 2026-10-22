#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN
UPDATE workflow_runs
SET
    run_status = 'rejected',
    current_round = 'decision',
    next_nodes = ARRAY[]::STRING[],
    state_version = state_version + 1,
    next_attempt_at = NULL,
    lease_owner = NULL,
    lease_acquired_at = NULL,
    last_heartbeat_at = NULL,
    lease_expires_at = NULL,
    updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running'
  AND graph_version = '2'
  AND lease_owner = 'explain-only-worker'
  AND lease_generation = 1
  AND lease_expires_at > now()
  AND state_version = 1
  AND latest_checkpoint_id = 'explain-only-checkpoint'
RETURNING return_request_id, state_version;

EXPLAIN
UPDATE return_requests
SET request_status = 'rejected', updated_at = now()
WHERE return_request_id = '00000000-0000-0000-0000-000000000001'::UUID
RETURNING return_request_id;

EXPLAIN
INSERT INTO approval_requests (
    run_id,
    request_number,
    refund_amount,
    currency,
    approval_reason
) VALUES (
    '00000000-0000-0000-0000-000000000000'::UUID,
    1,
    700.92,
    'USD',
    'Refund exceeds the manager threshold.'
);

EXPLAIN
SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
FROM audit_events
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID;

EXPLAIN
INSERT INTO audit_events (
    run_id,
    sequence_number,
    event_type,
    node_name,
    actor_type,
    checkpoint_id,
    event_data
) VALUES (
    '00000000-0000-0000-0000-000000000000'::UUID,
    1,
    'return_rejected',
    'decide_return',
    'system',
    'explain-only-checkpoint',
    '{"decision":{"reason_codes":["OUTSIDE_RETURN_WINDOW"]}}'::JSONB
);
SQL
