#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./config.sh

python scripts/smoke_test_return_quantity_reservations.py
