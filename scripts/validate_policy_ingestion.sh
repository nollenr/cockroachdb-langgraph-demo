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
  scripts/policy_document.py \
  scripts/ingest_return_policy.py

python -c "from pathlib import Path; import sys; sys.path.insert(0, 'scripts'); from policy_document import parse_policy_document; p = parse_policy_document(Path('$POLICY_SOURCE_URI')); assert len(p.sections) == 8; print('Policy parser validation successful: 8 identified sections')"
