#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN
INSERT INTO workflow_runs (
    run_id,
    return_request_id,
    thread_id,
    graph_version,
    current_round,
    next_nodes
) VALUES (
    '00000000-0000-0000-0000-000000000000'::UUID,
    '00000000-0000-0000-0000-000000000001'::UUID,
    'explain-only-thread',
    '1',
    'classification',
    ARRAY['classify_request']::STRING[]
);

EXPLAIN
SELECT
    run_id,
    return_request_id,
    thread_id,
    run_status,
    current_round,
    next_nodes,
    latest_checkpoint_id,
    state_version,
    graph_version,
    lease_owner,
    lease_generation,
    lease_acquired_at,
    last_heartbeat_at,
    lease_expires_at
FROM workflow_runs
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID;

-- Upgrade-only backfill used before migration 006 makes the column NOT NULL.
EXPLAIN
UPDATE workflow_runs
SET graph_version = '1'
WHERE graph_version IS NULL;

-- Scheduler lookup for running work whose owner stopped renewing its lease.
EXPLAIN
SELECT
    run_id,
    thread_id,
    return_request_id,
    lease_owner,
    lease_generation,
    latest_checkpoint_id,
    state_version,
    graph_version,
    lease_expires_at
FROM workflow_runs
WHERE run_status = 'running'
  AND lease_expires_at <= now()
ORDER BY lease_expires_at
LIMIT 20;

-- Atomic claim/reclaim. A real worker supplies the run ID and lease owner as
-- parameters and retains the returned generation as its fencing value.
EXPLAIN
UPDATE workflow_runs
SET
    run_status = 'running',
    next_attempt_at = NULL,
    lease_owner = 'explain-only-worker',
    lease_generation = lease_generation + 1,
    lease_acquired_at = now(),
    last_heartbeat_at = now(),
    lease_expires_at = now() + INTERVAL '30 seconds',
    updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND (
      run_status = 'ready'
      OR (run_status = 'retry_wait' AND next_attempt_at <= now())
      OR (run_status = 'running' AND lease_expires_at <= now())
  )
RETURNING run_id, lease_generation;

-- Renewal succeeds only for the current, still-live ownership generation.
EXPLAIN
UPDATE workflow_runs
SET
    last_heartbeat_at = now(),
    lease_expires_at = now() + INTERVAL '30 seconds',
    updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running'
  AND lease_owner = 'explain-only-worker'
  AND lease_generation = 1
  AND lease_expires_at > now()
RETURNING lease_generation, lease_expires_at;

-- Fenced publication combines ownership generation and optimistic state CAS.
EXPLAIN
UPDATE workflow_runs
SET
    latest_checkpoint_id = 'explain-only-checkpoint',
    state_version = state_version + 1,
    current_round = 'decision',
    next_nodes = ARRAY['decide_return']::STRING[],
    updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running'
  AND graph_version = '1'
  AND lease_owner = 'explain-only-worker'
  AND lease_generation = 1
  AND lease_expires_at > now()
  AND state_version = 0
RETURNING run_id, state_version;

-- Fenced release clears every active lease field atomically.
EXPLAIN
UPDATE workflow_runs
SET
    run_status = 'completed',
    next_attempt_at = NULL,
    lease_owner = NULL,
    lease_acquired_at = NULL,
    last_heartbeat_at = NULL,
    lease_expires_at = NULL,
    updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running'
  AND graph_version = '1'
  AND lease_owner = 'explain-only-worker'
  AND lease_generation = 1
  AND lease_expires_at > now()
RETURNING run_id, run_status;

EXPLAIN
DELETE FROM workflow_runs
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID;
SQL
