#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN SELECT o.order_number, o.currency, o.total_amount, o.ordered_at,
       c.external_customer_id, c.email,
       oi.order_item_id, oi.sku, oi.product_name,
       oi.product_category, oi.quantity, oi.line_total
FROM orders AS o
JOIN customers AS c ON c.customer_id = o.customer_id
JOIN order_items AS oi ON oi.order_id = o.order_id
WHERE o.order_number LIKE 'DEMO-%'
ORDER BY o.order_number, oi.order_item_id;

EXPLAIN SELECT c.customer_id, c.external_customer_id, o.order_id, o.order_number
FROM customers AS c JOIN orders AS o ON o.customer_id = c.customer_id
WHERE c.external_customer_id = 'CUST-RON' AND o.order_number = 'DEMO-1001';

EXPLAIN INSERT INTO return_requests (
  return_request_id, customer_id, order_id, request_text
) VALUES (
  'eeeeeeee-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001', 'explain only'
) RETURNING NOTHING;

EXPLAIN INSERT INTO workflow_runs (
  run_id, return_request_id, thread_id, graph_version, current_round, next_nodes
) VALUES (
  'eeeeeeee-0000-4000-8000-000000000002',
  'eeeeeeee-0000-4000-8000-000000000001', 'explain-only', '6',
  'classification', ARRAY['classify_request']::STRING[]
) RETURNING run_id, return_request_id, thread_id, run_status, graph_version, created_at;

EXPLAIN SELECT run_id FROM workflow_runs
WHERE graph_version = '6' AND (
  run_status = 'ready'
  OR (run_status = 'retry_wait' AND next_attempt_at <= now())
  OR (run_status = 'running' AND lease_expires_at <= now())
) ORDER BY updated_at, run_id LIMIT 10;

EXPLAIN SELECT wr.thread_id, c.external_customer_id, o.order_number, rr.request_text
FROM workflow_runs AS wr
JOIN return_requests AS rr ON rr.return_request_id = wr.return_request_id
JOIN customers AS c ON c.customer_id = rr.customer_id
JOIN orders AS o ON o.order_id = rr.order_id
WHERE wr.run_id = 'eeeeeeee-0000-4000-8000-000000000002';

EXPLAIN INSERT INTO node_attempts (
  run_id, node_name, attempt_number, attempt_status, input_state
)
SELECT 'eeeeeeee-0000-4000-8000-000000000002', 'classify_request',
       COALESCE(max(attempt_number), 0) + 1, 'started', '{}'::JSONB
FROM node_attempts
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
  AND node_name = 'classify_request'
RETURNING node_attempt_id;

EXPLAIN UPDATE node_attempts
SET attempt_status = 'succeeded', output_summary = '{}'::JSONB,
    error_code = NULL, error_message = NULL, finished_at = now(), duration_ms = 1
WHERE node_attempt_id = 'eeeeeeee-0000-4000-8000-000000000003'
  AND attempt_status = 'started'
RETURNING node_attempt_id;

EXPLAIN SELECT wr.run_id, wr.thread_id, wr.run_status, wr.current_round,
       wr.next_nodes, wr.latest_checkpoint_id, wr.state_version,
       wr.graph_version, wr.lease_generation, wr.created_at, wr.updated_at,
       rr.return_request_id, rr.request_text, rr.classified_intent,
       rr.request_status, c.external_customer_id, c.email, o.order_number,
       o.currency, o.total_amount
FROM workflow_runs AS wr
JOIN return_requests AS rr ON rr.return_request_id = wr.return_request_id
JOIN customers AS c ON c.customer_id = rr.customer_id
JOIN orders AS o ON o.order_id = rr.order_id
WHERE wr.run_id = 'eeeeeeee-0000-4000-8000-000000000002';

EXPLAIN SELECT node_attempt_id, node_name, attempt_number, attempt_status,
       input_state, output_summary, error_code, error_message,
       started_at, finished_at, duration_ms
FROM node_attempts
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
ORDER BY started_at, node_attempt_id;

EXPLAIN SELECT approval_request_id, approval_status, refund_amount, currency,
       approval_reason, requested_at, decided_at, decided_by, decision_note
FROM approval_requests
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
ORDER BY request_number DESC LIMIT 1;

EXPLAIN SELECT refund_id, refund_status, refund_amount, currency,
       payment_provider, provider_refund_id, idempotency_key, completed_at
FROM refunds WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002';

EXPLAIN SELECT sequence_number, event_type, node_name, actor_type, actor_id,
       checkpoint_id, event_data, occurred_at
FROM audit_events
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
ORDER BY sequence_number;

EXPLAIN UPDATE workflow_runs
SET run_status = 'rejected', current_round = 'classification',
    next_nodes = ARRAY[]::STRING[], state_version = state_version + 1,
    lease_owner = NULL, lease_acquired_at = NULL,
    last_heartbeat_at = NULL, lease_expires_at = NULL, updated_at = now()
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
  AND run_status = 'running' AND graph_version = '6'
  AND lease_owner = 'explain-worker' AND lease_generation = 1
  AND lease_expires_at > now() AND state_version = 1
  AND latest_checkpoint_id = 'explain-checkpoint'
RETURNING return_request_id, state_version;

EXPLAIN UPDATE return_requests
SET classified_intent = 'complaint', request_status = 'rejected', updated_at = now()
WHERE return_request_id = 'eeeeeeee-0000-4000-8000-000000000001'
RETURNING NOTHING;

EXPLAIN SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
FROM audit_events WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002';

EXPLAIN INSERT INTO audit_events (
  run_id, sequence_number, event_type, node_name, actor_type,
  checkpoint_id, event_data
) VALUES (
  'eeeeeeee-0000-4000-8000-000000000002', 1,
  'request_routed_out_of_refund', 'classify_request', 'system',
  'explain-checkpoint', '{}'::JSONB
) RETURNING NOTHING;

EXPLAIN SELECT return_request_id, thread_id, run_status
FROM workflow_runs
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
  AND thread_id LIKE 'returnflow-%'
FOR UPDATE;

EXPLAIN SELECT order_item_id, allocated_quantity, allocation_status
FROM return_item_allocations
WHERE return_request_id = 'eeeeeeee-0000-4000-8000-000000000001'
FOR UPDATE;

EXPLAIN UPDATE return_item_capacity
SET reserved_quantity = reserved_quantity - 1,
    refunded_quantity = refunded_quantity - 0,
    updated_at = now()
WHERE order_item_id = '40000000-0000-4000-8000-000000000001'
  AND reserved_quantity >= 1 AND refunded_quantity >= 0
RETURNING order_item_id;

EXPLAIN DELETE FROM audit_events
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002' RETURNING NOTHING;
EXPLAIN DELETE FROM node_attempts
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002' RETURNING NOTHING;
EXPLAIN DELETE FROM refund_attempts
WHERE refund_id IN (
  SELECT refund_id FROM refunds
  WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002'
) RETURNING NOTHING;
EXPLAIN DELETE FROM refunds
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002' RETURNING NOTHING;
EXPLAIN DELETE FROM return_item_allocations
WHERE return_request_id = 'eeeeeeee-0000-4000-8000-000000000001' RETURNING NOTHING;
EXPLAIN DELETE FROM return_items
WHERE return_request_id = 'eeeeeeee-0000-4000-8000-000000000001' RETURNING NOTHING;
EXPLAIN DELETE FROM approval_requests
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002' RETURNING NOTHING;
EXPLAIN DELETE FROM demo_payment_provider_refunds
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002' RETURNING NOTHING;
EXPLAIN DELETE FROM workflow_runs
WHERE run_id = 'eeeeeeee-0000-4000-8000-000000000002' RETURNING NOTHING;
EXPLAIN DELETE FROM return_requests
WHERE return_request_id = 'eeeeeeee-0000-4000-8000-000000000001' RETURNING NOTHING;
SQL
