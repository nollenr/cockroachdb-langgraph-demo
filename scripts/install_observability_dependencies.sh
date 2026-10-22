#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

cd "${REPO_DIR}"
source "${VENV_DIR}/bin/activate"

python -m pip install -r requirements.txt
python -m pip check
python -c "import opentelemetry.sdk, prometheus_client; print('Observability imports successful')"
