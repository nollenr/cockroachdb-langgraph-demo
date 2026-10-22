#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'

cd "$PROJECT_DIR"
mkdir -p /home/ec2-user/.local/state/product-returns/logs

GRAFANA_ADMIN_PASSWORD='configuration-validation-only' \
  docker-compose --project-directory "$PROJECT_DIR/observability" \
  -f "$PROJECT_DIR/observability/docker-compose.yml" config --quiet

python3.11 -m json.tool \
  "$PROJECT_DIR/observability/grafana/dashboards/graph-operations.json" \
  >/dev/null

echo 'Observability Compose and dashboard configuration are structurally valid.'
