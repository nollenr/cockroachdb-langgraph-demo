#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'

cd "$PROJECT_DIR"
source ./keys.sh
source ./api-key.sh
source ./config.sh
source /home/ec2-user/.venvs/product-returns/bin/activate

python scripts/check_observability_data.py
