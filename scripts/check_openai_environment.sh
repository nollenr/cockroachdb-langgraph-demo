#!/usr/bin/env bash

# Verify that the host-only OpenAI key is loaded and exported without ever
# printing its value. This script is intended to run on the AWS host.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo 'ERROR: OPENAI_API_KEY is not set after sourcing api-key.sh.' >&2
  exit 1
fi

if ! bash -c '[[ -n "${OPENAI_API_KEY:-}" ]]'; then
  echo 'ERROR: OPENAI_API_KEY is set but was not exported to child processes.' >&2
  exit 1
fi

echo 'OPENAI_API_KEY is set and exported to child processes.'
