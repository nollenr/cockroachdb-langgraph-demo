#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./config.sh
source ./api-key.sh

# Exercise failure injection, SQL inspection, and resume through the same
# Next.js proxy routes used by the presenter controls.
export RETURNFLOW_SMOKE_API_URL='http://127.0.0.1:3002/api'
python scripts/smoke_test_resilience_api.py
