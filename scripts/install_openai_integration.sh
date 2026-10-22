#!/usr/bin/env bash

# Install the fully reviewed/pinned project dependency set in the AWS-host
# virtual environment and verify the OpenAI embedding integration imports.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly VENV_DIR='/home/ec2-user/.venvs/product-returns'

cd "${REPO_DIR}"
source "${VENV_DIR}/bin/activate"

python -m pip install -r requirements.txt
python -m pip check
python -c "from langchain_openai import OpenAIEmbeddings; import openai; print('OpenAI integration imports successful')"
