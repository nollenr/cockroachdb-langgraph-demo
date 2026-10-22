#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR='/home/ec2-user/langchain/product-returns'

cd "${REPO_DIR}"
source ./keys.sh
source ./api-key.sh
source ./config.sh

cockroach sql --url "${CRDB_APP_URL}" --set=errexit=true --execute "
SHOW CREATE TABLE checkpoints;
SHOW CREATE TABLE checkpoint_blobs;
SHOW CREATE TABLE checkpoint_writes;
SHOW CREATE TABLE checkpoint_migrations;
"
