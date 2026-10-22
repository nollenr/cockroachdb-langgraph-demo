#!/usr/bin/env bash
# Check the configured cluster without printing credentials or connection URLs.
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh

error_file="$(mktemp)"
trap 'rm -f "${error_file}"' EXIT

if ! cockroach sql \
    --url "${CRDB_RON_ADMIN_URL}" \
    --format=tsv \
    --execute 'SELECT current_user(), version(); SHOW DATABASES;' \
    2>"${error_file}"; then
    echo 'Could not connect to the configured CockroachDB cluster as the owner.' >&2
    if grep -Eqi 'allowlist|not authorized|not permitted|not allowed|403|connection refused|i/o timeout|connection timed out' "${error_file}"; then
        echo 'Connection appears blocked by network access or the cluster IP allowlist.' >&2
    elif grep -Eqi 'password authentication failed|authentication failed|invalid password|28P01' "${error_file}"; then
        echo 'The owner credential was rejected.' >&2
    elif grep -Eqi 'no such host|name or service not known|DNS|lookup' "${error_file}"; then
        echo 'The configured cluster hostname could not be resolved.' >&2
    elif grep -Eqi 'certificate|tls|x509' "${error_file}"; then
        echo 'TLS certificate validation failed.' >&2
    else
        echo 'The connection error needs further classification; raw details are withheld.' >&2
    fi
    exit 1
fi
