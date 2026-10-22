#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN SELECT request_count
FROM demo_payment_provider_refunds
WHERE idempotency_key = 'product-returns:00000000-0000-0000-0000-000000000000:refund:v1';

EXPLAIN INSERT INTO refunds (
    run_id, return_request_id, idempotency_key, refund_status,
    refund_amount, currency, payment_provider
)
SELECT run_id, return_request_id,
       'product-returns:00000000-0000-0000-0000-000000000000:refund:v1',
       'processing', 53.99, 'USD', 'demo_payment_provider'
FROM workflow_runs
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running'
ON CONFLICT (run_id) DO UPDATE SET
    refund_status = CASE WHEN refunds.refund_status = 'succeeded'
                         THEN 'succeeded' ELSE 'processing' END,
    updated_at = now()
WHERE refunds.idempotency_key = excluded.idempotency_key
  AND refunds.refund_amount = excluded.refund_amount
  AND refunds.currency = excluded.currency
  AND refunds.payment_provider = excluded.payment_provider
RETURNING refund_id, return_request_id, idempotency_key, refund_status,
          refund_amount, currency, provider_refund_id;

EXPLAIN UPDATE refund_attempts
SET attempt_status = 'retryable_failure',
    error_code = 'WORKER_INTERRUPTED',
    error_message = 'A later attempt reclaimed this unfinished refund.',
    finished_at = now()
WHERE refund_id = '00000000-0000-0000-0000-000000000001'::UUID
  AND attempt_status = 'started';

EXPLAIN SELECT COALESCE(max(attempt_number), 0) + 1 AS attempt_number
FROM refund_attempts
WHERE refund_id = '00000000-0000-0000-0000-000000000001'::UUID;

EXPLAIN INSERT INTO refund_attempts (
    refund_id, attempt_number, attempt_status, provider_request_id
) VALUES (
    '00000000-0000-0000-0000-000000000001'::UUID, 1, 'started',
    'product-returns:00000000-0000-0000-0000-000000000000:refund:v1:attempt:1'
)
RETURNING refund_attempt_id;

EXPLAIN INSERT INTO demo_payment_provider_refunds (
    idempotency_key, run_id, refund_amount, currency, provider_status
) VALUES (
    'product-returns:00000000-0000-0000-0000-000000000000:refund:v1',
    '00000000-0000-0000-0000-000000000000'::UUID,
    53.99, 'USD', 'succeeded'
)
ON CONFLICT (idempotency_key) DO UPDATE SET
    request_count = demo_payment_provider_refunds.request_count + 1,
    last_requested_at = now()
WHERE demo_payment_provider_refunds.run_id = excluded.run_id
  AND demo_payment_provider_refunds.refund_amount = excluded.refund_amount
  AND demo_payment_provider_refunds.currency = excluded.currency
RETURNING provider_refund_id, request_count, provider_status;

EXPLAIN UPDATE refunds
SET refund_status = 'succeeded',
    provider_refund_id = '00000000-0000-0000-0000-000000000002',
    completed_at = COALESCE(completed_at, now()), updated_at = now()
WHERE refund_id = '00000000-0000-0000-0000-000000000001'::UUID
  AND idempotency_key = 'product-returns:00000000-0000-0000-0000-000000000000:refund:v1'
  AND refund_status IN ('processing', 'succeeded')
  AND (provider_refund_id IS NULL OR provider_refund_id = '00000000-0000-0000-0000-000000000002');

EXPLAIN UPDATE refund_attempts
SET attempt_status = 'succeeded',
    provider_response = '{"provider_status":"succeeded"}'::JSONB,
    finished_at = now()
WHERE refund_attempt_id = '00000000-0000-0000-0000-000000000003'::UUID
  AND attempt_status = 'started';

EXPLAIN UPDATE workflow_runs
SET run_status = 'completed', current_round = 'completed',
    next_nodes = ARRAY[]::STRING[], state_version = state_version + 1,
    next_attempt_at = NULL, lease_owner = NULL, lease_acquired_at = NULL,
    last_heartbeat_at = NULL, lease_expires_at = NULL, updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND run_status = 'running' AND graph_version = '4'
  AND lease_owner = 'explain-worker' AND lease_generation = 1
  AND lease_expires_at > now() AND state_version = 1
  AND latest_checkpoint_id = 'explain-checkpoint'
RETURNING return_request_id, state_version;

EXPLAIN SELECT refund_id
FROM refunds
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID
  AND refund_id = '00000000-0000-0000-0000-000000000001'::UUID
  AND idempotency_key = 'product-returns:00000000-0000-0000-0000-000000000000:refund:v1'
  AND refund_status = 'succeeded'
  AND provider_refund_id = '00000000-0000-0000-0000-000000000002';

EXPLAIN UPDATE return_requests
SET request_status = 'refunded', updated_at = now()
WHERE return_request_id = '00000000-0000-0000-0000-000000000004'::UUID;

EXPLAIN SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
FROM audit_events
WHERE run_id = '00000000-0000-0000-0000-000000000000'::UUID;

EXPLAIN INSERT INTO audit_events (
    run_id, sequence_number, event_type, node_name, actor_type,
    actor_id, checkpoint_id, event_data
) VALUES (
    '00000000-0000-0000-0000-000000000000'::UUID, 2,
    'refund_succeeded', 'issue_refund', 'payment_provider',
    'demo_payment_provider', 'explain-checkpoint',
    '{"refund":{"refund_status":"succeeded"}}'::JSONB
);
SQL
