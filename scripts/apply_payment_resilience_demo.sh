#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./api-key.sh
source ./config.sh
cockroach sql --url "$CRDB_RON_URL" --file migrations/013_payment_resilience_demo.sql
