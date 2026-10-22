#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" --set=errexit=true \
  --file migrations/011_bob_fraud_review_order.sql
