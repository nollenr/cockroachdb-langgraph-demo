#!/usr/bin/env bash
set -euo pipefail

check_url() {
  local name="$1"
  local url="$2"
  local attempt

  for attempt in {1..15}; do
    if curl --fail --silent --show-error --max-time 3 "$url" >/dev/null 2>&1; then
      echo "PASS ${name}: ${url}"
      return 0
    fi
    sleep 2
  done

  echo "FAIL ${name}: ${url}" >&2
  return 1
}

check_url 'Grafana' 'http://127.0.0.1:3001/api/health'
check_url 'Prometheus' 'http://127.0.0.1:9091/-/ready'
check_url 'Tempo' 'http://127.0.0.1:3200/ready'
check_url 'Loki' 'http://127.0.0.1:3100/ready'
check_url 'Alloy' 'http://127.0.0.1:12345/-/ready'

echo 'Container restart counts:'
for container in \
  product-returns-observability-grafana-1 \
  product-returns-observability-prometheus-1 \
  product-returns-observability-tempo-1 \
  product-returns-observability-loki-1 \
  product-returns-observability-alloy-1; do
  docker inspect --format '{{.Name}} status={{.State.Status}} restarts={{.RestartCount}}' "$container"
done
