#!/usr/bin/env bash
# Apply the reviewed schema migrations to a fresh product_returns database.
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

error_file="$(mktemp)"
trap 'rm -f "${error_file}"' EXIT

for migration in \
    001_runtime_privileges \
    002_business_schema \
    003_workflow_schema \
    005_observability_schema \
    006_workflow_leases \
    007_demo_payment_provider \
    008_return_quantity_reservations \
    009_return_allocation_covering_index \
    010_workflow_node_events \
    012_resilience_demo \
    013_payment_resilience_demo \
    001_runtime_privileges; do
    if ! cockroach sql \
        --url "${CRDB_RON_URL}" \
        --set=errexit=true \
        --file "migrations/${migration}.sql" \
        >"${error_file}" 2>&1; then
        echo "Migration ${migration} failed; raw output was withheld because it may include a connection URL." >&2
        exit 1
    fi
    echo "Applied ${migration}."
done
