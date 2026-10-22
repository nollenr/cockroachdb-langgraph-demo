#!/usr/bin/env bash

# Apply the already EXPLAINed and rollback-tested deterministic demo fixtures
# as the least-privilege runtime identity.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql \
  --url "${CRDB_APP_URL}" \
  --set=errexit=true \
  --file migrations/004_demo_seed.sql
