#!/usr/bin/env bash
# Read-only summary of a fresh demo deployment.
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_RON_URL}" --format=tsv <<'SQL'
SELECT count(*) AS public_tables
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

SELECT count(*) AS app_table_crud_grants
FROM information_schema.table_privileges
WHERE table_schema = 'public'
  AND grantee = 'product_returns_app'
  AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE');

SELECT count(*) AS demo_orders FROM orders WHERE order_number LIKE 'DEMO-%';
SELECT count(*) AS policy_chunks FROM policy_chunks WHERE namespace = 'standard-returns:1.0';
SELECT count(*) AS active_synthetic_runs FROM workflow_runs WHERE thread_id LIKE 'returnflow-%';

SELECT count(*) AS capacity_rows,
       sum(purchased_quantity) AS purchased_units,
       sum(reserved_quantity) AS reserved_units,
       sum(refunded_quantity) AS refunded_units
FROM return_item_capacity;

SELECT count(*) AS historical_refunded_allocations
FROM return_item_allocations
WHERE allocation_status = 'refunded';
SQL
