#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DIR="/home/ec2-user/langchain/product-returns"
readonly STATE_DIR="/home/ec2-user/.local/state/product-returns/api"
readonly PID_FILE="${STATE_DIR}/server.pid"
readonly LOG_FILE="${STATE_DIR}/server.log"
readonly HEALTH_URL="http://127.0.0.1:8010/health"

mkdir -p "${STATE_DIR}"

if [[ -f "${PID_FILE}" ]]; then
    existing_pid="$(<"${PID_FILE}")"
    if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
        echo "ReturnFlow API is already running with PID ${existing_pid}."
        exit 0
    fi
    rm -f "${PID_FILE}"
fi

if ss -ltn | grep -q ':8010 '; then
    echo "Port 8010 is already in use by an unmanaged process." >&2
    exit 1
fi

cd "${REPO_DIR}"
source /home/ec2-user/.venvs/product-returns/bin/activate
source ./keys.sh
source ./config.sh
source ./api-key.sh

nohup python -m uvicorn product_returns.api:app \
    --host 127.0.0.1 --port 8010 --workers 1 \
    >"${LOG_FILE}" 2>&1 </dev/null &
api_pid=$!
printf '%s\n' "${api_pid}" >"${PID_FILE}"

for _ in {1..45}; do
    if curl --fail --silent --output /dev/null "${HEALTH_URL}"; then
        echo "ReturnFlow API is ready on localhost:8010 with PID ${api_pid}."
        echo "Log: ${LOG_FILE}"
        exit 0
    fi
    if ! kill -0 "${api_pid}" 2>/dev/null; then
        echo "ReturnFlow API exited before becoming healthy." >&2
        tail -n 60 "${LOG_FILE}" >&2
        rm -f "${PID_FILE}"
        exit 1
    fi
    sleep 1
done

echo "ReturnFlow API did not become healthy within 45 seconds." >&2
kill "${api_pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
exit 1
