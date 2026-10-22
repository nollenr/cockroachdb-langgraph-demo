#!/usr/bin/env bash

# Execute every seed statement inside its transaction, but replace COMMIT with
# ROLLBACK so constraints and values are validated without persisting rows.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly SEED_FILE='migrations/004_demo_seed.sql'

cd "${REPO_DIR}"
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./api-key.sh
source ./config.sh

sed -E 's/^COMMIT;$/ROLLBACK;/' "${SEED_FILE}" |
  cockroach sql --url "${CRDB_APP_URL}" --set=errexit=true
