#!/usr/bin/env bash
# Create package-owned checkpoint tables and grant the app login runtime access.
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

error_file="$(mktemp)"
trap 'rm -f "${error_file}"' EXIT

if ! /home/ec2-user/.venvs/product-returns/bin/python \
    scripts/setup_langgraph_checkpoint.py >"${error_file}" 2>&1; then
    echo 'LangGraph checkpoint setup failed; raw output was withheld because it may include a connection URL.' >&2
    exit 1
fi
echo 'LangGraph checkpoint setup completed.'

if ! cockroach sql \
    --url "${CRDB_RON_URL}" \
    --set=errexit=true \
    --file migrations/001_runtime_privileges.sql \
    >"${error_file}" 2>&1; then
    echo 'Post-checkpoint runtime grants failed; raw output was withheld because it may include a connection URL.' >&2
    exit 1
fi
echo 'Post-checkpoint runtime grants applied.'
