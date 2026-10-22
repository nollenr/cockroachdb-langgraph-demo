#!/usr/bin/env bash

# Resolve, but do not install, the current langchain-openai release against the
# project's existing AWS-host virtual environment.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

cd "${REPO_DIR}"
source "${VENV_DIR}/bin/activate"

python -m pip install --dry-run langchain-openai
