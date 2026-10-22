#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'
CONTAINER='product-returns-observability-grafana-1'

cd "$PROJECT_DIR"
source ./keys.sh

echo 'Mounted dashboard files:'
docker exec "$CONTAINER" \
  find /var/lib/grafana/dashboards -maxdepth 2 -type f -print

echo 'Mounted provisioning files:'
docker exec "$CONTAINER" \
  find /etc/grafana/provisioning -maxdepth 3 -type f -print

echo 'Grafana provisioning-related log lines:'
docker logs --tail 300 "$CONTAINER" 2>&1 \
  | grep -Ei 'provision|dashboard|error|failed' \
  | tail -n 100 || true

python3.11 scripts/diagnose_grafana.py
