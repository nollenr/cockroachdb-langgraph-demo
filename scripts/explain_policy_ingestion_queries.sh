#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" --set=errexit=true --execute "
EXPLAIN SELECT
    rp.return_policy_id,
    rp.title,
    rp.policy_key,
    rp.policy_version,
    rp.source_uri,
    rp.content_sha256,
    pc.policy_clause_id,
    pc.clause_key,
    pc.clause_text,
    pc.display_order
FROM return_policies AS rp
JOIN policy_clauses AS pc
  ON pc.return_policy_id = rp.return_policy_id
WHERE rp.policy_key = 'standard-returns'
  AND rp.policy_version = '1.0'
  AND rp.policy_status = 'active'
ORDER BY pc.display_order;

EXPLAIN SELECT id, content, metadata
FROM policy_chunks
WHERE namespace = 'standard-returns:1.0'
ORDER BY id;
"
