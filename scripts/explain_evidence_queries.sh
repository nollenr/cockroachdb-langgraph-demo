#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

cd "${REPO_DIR}"
source "${VENV_DIR}/bin/activate"
source ./keys.sh
source ./api-key.sh
source ./config.sh

python -m py_compile product_returns/evidence.py scripts/explain_evidence_queries.py
python scripts/explain_evidence_queries.py
