#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_RON_URL}" \
  --file migrations/006_workflow_leases.sql

# Cover the newly added columns with the existing runtime-table grants and
# print the effective privileges for review.
cockroach sql --url "${CRDB_RON_URL}" \
  --file migrations/001_runtime_privileges.sql
