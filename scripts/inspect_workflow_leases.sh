#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_RON_URL}" --execute \
  'SHOW CREATE TABLE workflow_runs; SHOW CONSTRAINTS FROM workflow_runs; SHOW INDEXES FROM workflow_runs;'
