#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'

cd "$PROJECT_DIR"
source ./keys.sh
source ./api-key.sh
source ./config.sh

: "${GRAFANA_ADMIN_PASSWORD:?GRAFANA_ADMIN_PASSWORD is not exported by keys.sh}"

echo 'Grafana administrator password is present (value not displayed).'
echo 'Existing Docker containers:'
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'

echo 'Existing Compose projects:'
docker-compose ls -a

for port in 3001 3100 3200 4317 4318 9091 12345; do
  if ss -lnt "sport = :${port}" | tail -n +2 | grep -q .; then
    echo "ERROR: required Product Returns port ${port} is already listening." >&2
    exit 1
  fi
done

echo 'Product Returns observability ports are available.'
