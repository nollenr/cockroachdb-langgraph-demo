#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./config.sh
source ./api-key.sh
python scripts/smoke_test_returnflow_denial_api.py
