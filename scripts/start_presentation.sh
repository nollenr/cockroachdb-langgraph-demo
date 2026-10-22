#!/usr/bin/env bash
set -euo pipefail

readonly APP_DIR="/home/ec2-user/langchain/product-returns/presentation"
readonly STATE_DIR="/home/ec2-user/.local/state/product-returns/presentation"
readonly PID_FILE="${STATE_DIR}/server.pid"
readonly LOG_FILE="${STATE_DIR}/server.log"
readonly HEALTH_URL="http://127.0.0.1:3002/"

mkdir -p "${STATE_DIR}"

if [[ -f "${PID_FILE}" ]]; then
    existing_pid="$(<"${PID_FILE}")"
    if [[ "${existing_pid}" =~ ^[0-9]+$ ]] && kill -0 "${existing_pid}" 2>/dev/null; then
        echo "ReturnFlow is already running with PID ${existing_pid}."
        exit 0
    fi
    rm -f "${PID_FILE}"
fi

if ss -ltn | grep -q ':3002 '; then
    echo "Port 3002 is already in use by a process not managed by ${PID_FILE}." >&2
    exit 1
fi

cd "${APP_DIR}"
nohup npm start >"${LOG_FILE}" 2>&1 </dev/null &
presentation_pid=$!
printf '%s\n' "${presentation_pid}" >"${PID_FILE}"

for _ in {1..20}; do
    if curl --fail --silent --output /dev/null "${HEALTH_URL}"; then
        echo "ReturnFlow is ready on port 3002 with PID ${presentation_pid}."
        echo "Log: ${LOG_FILE}"
        exit 0
    fi
    if ! kill -0 "${presentation_pid}" 2>/dev/null; then
        echo "ReturnFlow exited before becoming healthy." >&2
        tail -n 40 "${LOG_FILE}" >&2
        rm -f "${PID_FILE}"
        exit 1
    fi
    sleep 1
done

echo "ReturnFlow did not become healthy within 20 seconds." >&2
kill "${presentation_pid}" 2>/dev/null || true
rm -f "${PID_FILE}"
exit 1
