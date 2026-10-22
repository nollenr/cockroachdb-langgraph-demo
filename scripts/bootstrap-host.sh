#!/usr/bin/env bash

# Bootstrap only the isolated Python runtime on the AWS host. Project
# dependencies are deliberately installed in a later, version-pinned step.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

if [[ ! -f "${REPO_DIR}/PROJECT-STATUS.md" ]]; then
  echo "Repository synchronization is incomplete: ${REPO_DIR}/PROJECT-STATUS.md is missing." >&2
  exit 1
fi

mkdir -p '/home/ec2-user/.venvs'
python3.11 -m venv "${VENV_DIR}"

echo "Repository synchronized at: ${REPO_DIR}"
"${VENV_DIR}/bin/python" --version
"${VENV_DIR}/bin/python" -m pip --version
