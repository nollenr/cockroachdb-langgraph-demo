#!/usr/bin/env bash

# Parse and plan every generated DML/verification statement without applying
# seed data. Run on AWS after WinSCP has synchronized the repository.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'
readonly SEED_FILE='migrations/004_demo_seed.sql'

cd "${REPO_DIR}"
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./api-key.sh
source ./config.sh

# Prefix top-level UPSERT and SELECT statements with EXPLAIN. BEGIN/COMMIT and
# USE remain harmless; EXPLAIN prevents every data-changing statement from
# executing while CockroachDB still parses, plans, and resolves all objects.
sed -E '/^(UPSERT INTO|SELECT([[:space:]]|$))/s/^/EXPLAIN /' "${SEED_FILE}" |
  cockroach sql --url "${CRDB_APP_URL}" --set=errexit=true
