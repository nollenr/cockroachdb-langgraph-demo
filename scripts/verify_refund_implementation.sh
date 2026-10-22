#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./config.sh

python scripts/print_graph_signature.py
python -c 'from product_returns.graph_version import validate_graph_definition, validate_deployment_graph_version; validate_graph_definition(); validate_deployment_graph_version(); print("Graph version validation passed.")'

cockroach sql --url "${CRDB_APP_URL}" <<'SQL'
SELECT count(*) AS table_count
FROM information_schema.tables
WHERE table_catalog = current_database()
  AND table_schema = 'public'
  AND table_type = 'BASE TABLE';

SELECT count(*) AS runtime_table_grant_count
FROM information_schema.table_privileges
WHERE table_catalog = current_database()
  AND table_schema = 'public'
  AND grantee = 'product_returns_app'
  AND privilege_type IN ('SELECT', 'INSERT', 'UPDATE', 'DELETE');

SELECT
    (SELECT count(*) FROM workflow_runs) AS workflow_run_count,
    (SELECT count(*) FROM refunds) AS refund_count,
    (SELECT count(*) FROM refund_attempts) AS refund_attempt_count,
    (SELECT count(*) FROM demo_payment_provider_refunds) AS provider_refund_count,
    (SELECT count(*) FROM return_item_allocations
      WHERE allocation_status = 'reserved') AS active_reservation_count,
    (SELECT count(*) FROM return_item_capacity
      WHERE reserved_quantity + refunded_quantity > purchased_quantity)
      AS capacity_violation_count;
SQL
