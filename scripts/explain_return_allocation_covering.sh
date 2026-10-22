#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
EXPLAIN SELECT allocated_quantity, allocation_status
FROM return_item_allocations
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID
  AND order_item_id = '00000000-0000-0000-0000-000000000003'::UUID;

EXPLAIN SELECT order_item_id, allocated_quantity
FROM return_item_allocations
WHERE return_request_id = '00000000-0000-0000-0000-000000000002'::UUID
  AND allocation_status = 'reserved'
ORDER BY order_item_id
FOR UPDATE;
SQL
