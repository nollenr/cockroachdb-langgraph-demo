#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

cd "${REPO_DIR}"
source "${VENV_DIR}/bin/activate"
source ./keys.sh
source ./api-key.sh
source ./config.sh

python -m py_compile \
  product_returns/state.py \
  product_returns/approval.py \
  product_returns/approval_store.py \
  product_returns/graph.py \
  product_returns/graph_version.py \
  product_returns/workflow_worker.py \
  scripts/manager_decision.py \
  scripts/smoke_test_approval_interrupt.py
python scripts/smoke_test_approval_interrupt.py
