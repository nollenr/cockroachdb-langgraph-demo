#!/usr/bin/env bash
set -euo pipefail

cd /home/ec2-user/langchain/product-returns
source ./keys.sh
source ./config.sh
exec /home/ec2-user/.venvs/product-returns/bin/python \
    scripts/create_database_and_user.py
