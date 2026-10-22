#!/usr/bin/env bash
set -euo pipefail

echo '=== compute ==='
nproc
free -h

echo '=== storage ==='
df -h / /home/ec2-user

echo '=== container runtimes ==='
for command_name in docker podman docker-compose; do
  if command -v "${command_name}" >/dev/null 2>&1; then
    "${command_name}" --version
  else
    echo "${command_name}: not installed"
  fi
done

echo '=== listening observability ports ==='
ss -lnt | awk 'NR == 1 || $4 ~ /:(3000|3001|3100|3200|4317|4318|9090|9091|12345)$/ { print }'

echo '=== existing services ==='
systemctl list-unit-files --type=service --no-pager \
  | awk 'NR == 1 || /grafana|prometheus|tempo|loki|alloy|docker|podman/'
