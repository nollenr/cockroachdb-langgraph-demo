#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR='/home/ec2-user/langchain/product-returns'

docker-compose --project-directory "$PROJECT_DIR/observability" \
  -f "$PROJECT_DIR/observability/docker-compose.yml" down

echo 'Product Returns observability containers stopped; named data volumes were retained.'
