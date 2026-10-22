#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN SELECT wr.return_request_id, rr.order_id
FROM workflow_runs AS wr
JOIN return_requests AS rr ON rr.return_request_id = wr.return_request_id
WHERE wr.run_id = '00000000-0000-0000-0000-000000000001'::UUID
  AND wr.run_status = 'running'
FOR UPDATE OF rr;

EXPLAIN SELECT allocated_quantity, allocation_status
FROM return_item_allocations
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID
  AND order_item_id = '00000000-0000-0000-0000-000000000003'::UUID;

EXPLAIN SELECT purchased_quantity, reserved_quantity, refunded_quantity
FROM return_item_capacity
WHERE order_item_id = '00000000-0000-0000-0000-000000000003'::UUID;

EXPLAIN INSERT INTO return_item_capacity (order_item_id, purchased_quantity)
SELECT order_item_id, quantity
FROM order_items
WHERE order_item_id = '00000000-0000-0000-0000-000000000003'::UUID
  AND order_id = '00000000-0000-0000-0000-000000000004'::UUID
ON CONFLICT (order_item_id) DO NOTHING;

EXPLAIN UPDATE return_item_capacity
SET reserved_quantity = reserved_quantity + 1, updated_at = now()
WHERE order_item_id = '00000000-0000-0000-0000-000000000003'::UUID
  AND purchased_quantity - reserved_quantity - refunded_quantity >= 1
RETURNING purchased_quantity,
          reserved_quantity - 1 AS reserved_before,
          refunded_quantity;

EXPLAIN INSERT INTO return_items (
    return_request_id, order_item_id, requested_quantity,
    return_reason, requested_refund_amount
) VALUES (
    '00000000-0000-0000-0000-000000000002'::UUID,
    '00000000-0000-0000-0000-000000000003'::UUID,
    1, 'Explain only.', 53.99
)
ON CONFLICT (return_request_id, order_item_id) DO NOTHING;

EXPLAIN INSERT INTO return_item_allocations (
    return_request_id, order_item_id, allocated_quantity, allocation_status
) VALUES (
    '00000000-0000-0000-0000-000000000002'::UUID,
    '00000000-0000-0000-0000-000000000003'::UUID,
    1, 'reserved'
);

EXPLAIN SELECT order_item_id, allocated_quantity
FROM return_item_allocations
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID
  AND allocation_status = 'reserved'
ORDER BY order_item_id
FOR UPDATE;

EXPLAIN UPDATE return_item_capacity
SET reserved_quantity = reserved_quantity - 1, updated_at = now()
WHERE order_item_id = '00000000-0000-0000-0000-000000000003'::UUID
  AND reserved_quantity >= 1;

EXPLAIN UPDATE return_item_allocations
SET allocation_status = 'released', updated_at = now()
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID
  AND allocation_status = 'reserved';

EXPLAIN UPDATE return_item_capacity
SET reserved_quantity = reserved_quantity - 1,
    refunded_quantity = refunded_quantity + 1,
    updated_at = now()
WHERE order_item_id = '00000000-0000-0000-0000-000000000003'::UUID
  AND reserved_quantity >= 1
  AND refunded_quantity + 1 <= purchased_quantity;

EXPLAIN UPDATE return_item_allocations
SET allocation_status = 'refunded', updated_at = now()
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID
  AND allocation_status = 'reserved';

EXPLAIN UPDATE workflow_runs
SET run_status = 'rejected', current_round = 'reservation',
    next_nodes = ARRAY[]::STRING[], state_version = state_version + 1,
    next_attempt_at = NULL, lease_owner = NULL, lease_acquired_at = NULL,
    last_heartbeat_at = NULL, lease_expires_at = NULL, updated_at = now()
WHERE run_id = '00000000-0000-0000-0000-000000000001'::UUID
  AND run_status = 'running' AND graph_version = '6'
  AND lease_owner = 'explain-worker' AND lease_generation = 1
  AND lease_expires_at > now() AND state_version = 1
  AND latest_checkpoint_id = 'explain-checkpoint'
RETURNING return_request_id, state_version;

EXPLAIN UPDATE return_requests
SET request_status = 'rejected', updated_at = now()
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID;

EXPLAIN SELECT COALESCE(max(sequence_number), 0) + 1 AS next_sequence
FROM audit_events
WHERE run_id = '00000000-0000-0000-0000-000000000001'::UUID;

EXPLAIN INSERT INTO audit_events (
    run_id, sequence_number, event_type, node_name,
    actor_type, checkpoint_id, event_data
) VALUES (
    '00000000-0000-0000-0000-000000000001'::UUID, 1,
    'return_quantity_unavailable', 'reserve_return_items',
    'system', 'explain-checkpoint',
    '{"reservation":{"status":"conflict"}}'::JSONB
);

EXPLAIN INSERT INTO return_item_allocations (
    return_item_allocation_id, return_request_id, order_item_id,
    allocated_quantity, allocation_status, created_at, updated_at
)
SELECT ri.return_item_id, ri.return_request_id, ri.order_item_id,
       ri.requested_quantity,
       CASE WHEN rr.request_status = 'refunded' THEN 'refunded'
            WHEN rr.request_status IN (
                'received', 'classifying', 'gathering_evidence',
                'pending_approval', 'approved', 'refunding'
            ) THEN 'reserved' ELSE 'released' END,
       ri.created_at, rr.updated_at
FROM return_items AS ri
JOIN return_requests AS rr ON rr.return_request_id = ri.return_request_id
ON CONFLICT (return_request_id, order_item_id) DO NOTHING;

EXPLAIN INSERT INTO return_item_capacity (
    order_item_id, purchased_quantity, reserved_quantity, refunded_quantity
)
SELECT oi.order_item_id, oi.quantity,
       COALESCE(sum(a.allocated_quantity) FILTER (
           WHERE a.allocation_status = 'reserved'), 0)::INT8,
       COALESCE(sum(a.allocated_quantity) FILTER (
           WHERE a.allocation_status = 'refunded'), 0)::INT8
FROM order_items AS oi
LEFT JOIN return_item_allocations AS a ON a.order_item_id = oi.order_item_id
GROUP BY oi.order_item_id, oi.quantity
ON CONFLICT (order_item_id) DO UPDATE SET
    purchased_quantity = excluded.purchased_quantity,
    reserved_quantity = excluded.reserved_quantity,
    refunded_quantity = excluded.refunded_quantity,
    updated_at = now();
SQL
