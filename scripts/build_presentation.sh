#!/usr/bin/env bash
set -euo pipefail

readonly APP_DIR='/home/ec2-user/langchain/product-returns/presentation'

cd "${APP_DIR}"
npm run typecheck
npm run build
