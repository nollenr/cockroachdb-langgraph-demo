#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'

cd "$PROJECT_DIR"
source ./keys.sh
source ./api-key.sh
source ./config.sh

: "${GRAFANA_ADMIN_PASSWORD:?Set and export GRAFANA_ADMIN_PASSWORD in keys.sh}"

mkdir -p /home/ec2-user/.local/state/product-returns/logs

docker-compose --project-directory "$PROJECT_DIR/observability" \
  -f "$PROJECT_DIR/observability/docker-compose.yml" up -d

docker-compose --project-directory "$PROJECT_DIR/observability" \
  -f "$PROJECT_DIR/observability/docker-compose.yml" ps
