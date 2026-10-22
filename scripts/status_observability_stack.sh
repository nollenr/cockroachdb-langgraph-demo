#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'

export GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-status-check-placeholder}"

docker-compose --project-directory "$PROJECT_DIR/observability" \
  -f "$PROJECT_DIR/observability/docker-compose.yml" ps
