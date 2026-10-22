#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./config.sh

cockroach sql --url "${CRDB_RON_URL}" \
  --file migrations/010_workflow_node_events.sql
cockroach sql --url "${CRDB_RON_URL}" \
  --file migrations/001_runtime_privileges.sql
