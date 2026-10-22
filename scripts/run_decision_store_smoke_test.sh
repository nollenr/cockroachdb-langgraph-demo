#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

cd "${REPO_DIR}"
source "${VENV_DIR}/bin/activate"
source ./keys.sh
source ./config.sh

python -m py_compile \
  product_returns/state.py \
  product_returns/graph_version.py \
  product_returns/workflow_runs.py \
  product_returns/decision_store.py \
  scripts/smoke_test_decision_store.py
python scripts/smoke_test_decision_store.py
