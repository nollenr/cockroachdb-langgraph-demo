#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN UPDATE approval_requests
SET approval_status = 'approved', decided_at = now(),
    decided_by = 'explain-manager', decision_note = 'explain only'
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND approval_status = 'pending'
RETURNING approval_request_id, decided_at;

EXPLAIN UPDATE workflow_runs
SET run_status = 'ready', current_round = 'approval_resume',
    state_version = state_version + 1, updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'waiting_for_approval'
  AND graph_version = '3'
  AND latest_checkpoint_id IS NOT NULL
  AND next_nodes @> ARRAY['await_manager_approval']::STRING[]
RETURNING latest_checkpoint_id, state_version;

EXPLAIN SELECT approval_status, decided_by, decision_note, decided_at
FROM approval_requests
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND approval_status IN ('approved', 'rejected')
ORDER BY request_number DESC
LIMIT 1;

EXPLAIN UPDATE workflow_runs
SET run_status = 'ready', current_round = 'refund',
    next_nodes = ARRAY['issue_refund']::STRING[],
    state_version = state_version + 1,
    lease_owner = NULL, lease_acquired_at = NULL,
    last_heartbeat_at = NULL, lease_expires_at = NULL,
    updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running'
  AND graph_version = '3'
  AND lease_owner = 'explain-worker'
  AND lease_generation = 2
  AND lease_expires_at > now()
  AND state_version = 4
  AND latest_checkpoint_id = 'explain-resumed-checkpoint'
RETURNING return_request_id, state_version;

EXPLAIN UPDATE return_requests
SET request_status = 'approved', updated_at = now()
WHERE return_request_id = '00000000-0000-0000-0000-000000000001'::UUID;

EXPLAIN SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
FROM audit_events
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID;

EXPLAIN INSERT INTO audit_events (
    run_id, sequence_number, event_type, node_name, actor_type,
    actor_id, checkpoint_id, event_data
) VALUES (
    '00000000-0000-0000-0000-000000000000'::UUID,
    2,
    'manager_approved',
    'await_manager_approval',
    'manager',
    'explain-manager',
    'explain-checkpoint',
    '{"manager_decision":{"decision":"approved"}}'::JSONB
);
SQL
