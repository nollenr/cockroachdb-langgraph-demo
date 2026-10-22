#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_RON_URL}" \
  --file migrations/005_observability_schema.sql

cockroach sql --url "${CRDB_RON_URL}" \
  --file migrations/001_runtime_privileges.sql

