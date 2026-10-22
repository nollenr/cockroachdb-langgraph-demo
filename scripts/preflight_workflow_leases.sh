#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

if ! grep -q 'workflow_runs_by_expired_lease' migrations/006_workflow_leases.sql; then
  echo 'ERROR: WinSCP has not synchronized migration 006 yet.' >&2
  exit 1
fi

cockroach sql --url "${CRDB_RON_URL}" <<'SQL'
SELECT
    count(*) AS workflow_run_count,
    count(*) FILTER (WHERE run_status = 'running') AS running_count
FROM workflow_runs;

SHOW CREATE TABLE workflow_runs;
SQL
