#!/usr/bin/env bash

# Rerun the business schema to create policy_chunks, refresh runtime grants,
# and display the resulting CockroachDB table definition and privileges.
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

if ! grep -q 'CREATE TABLE IF NOT EXISTS policy_chunks' \
  migrations/002_business_schema.sql; then
  echo 'ERROR: WinSCP has not synchronized the updated migration yet.' >&2
  exit 1
fi

cockroach sql \
  --url "${CRDB_RON_URL}" \
  --set=errexit=true \
  --file migrations/002_business_schema.sql

cockroach sql \
  --url "${CRDB_RON_URL}" \
  --set=errexit=true \
  --file migrations/001_runtime_privileges.sql

cockroach sql \
  --url "${CRDB_RON_URL}" \
  --set=errexit=true \
  --execute 'SHOW CREATE TABLE policy_chunks; SHOW GRANTS ON TABLE policy_chunks;'

# Validate the shape of the future cosine-distance retrieval query. The
# subquery supplies a same-dimension vector without placing a 1,536-element
# literal in this diagnostic; the table may be empty at this stage.
cockroach sql \
  --url "${CRDB_APP_URL}" \
  --set=errexit=true \
  --execute "EXPLAIN SELECT candidate.id, candidate.content, candidate.metadata FROM policy_chunks AS candidate CROSS JOIN (SELECT embedding FROM policy_chunks LIMIT 1) AS query_vector WHERE candidate.namespace = 'standard-returns:1.0' ORDER BY candidate.embedding <=> query_vector.embedding LIMIT 4;"
