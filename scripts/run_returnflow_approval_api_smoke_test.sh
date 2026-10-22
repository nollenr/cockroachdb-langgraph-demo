#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./config.sh
source ./api-key.sh

# Exercise manager approval through the same Next.js proxy used by the browser.
export RETURNFLOW_SMOKE_API_URL='http://127.0.0.1:3002/api'
python scripts/smoke_test_returnflow_approval_api.py
