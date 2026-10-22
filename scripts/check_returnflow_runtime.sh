#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

printf 'API '
curl --fail --silent --show-error http://127.0.0.1:8010/health
printf '\nPROXY '
curl --fail --silent --show-error http://127.0.0.1:3002/api/health
printf '\n'

cockroach sql --url "${CRDB_APP_URL}" --format=tsv <<'SQL'
SELECT count(*) AS synthetic_runs
FROM workflow_runs
WHERE thread_id LIKE 'returnflow-%';

SELECT purchased_quantity, reserved_quantity, refunded_quantity
FROM return_item_capacity
WHERE order_item_id = '40000000-0000-4000-8000-000000000001';
SQL
