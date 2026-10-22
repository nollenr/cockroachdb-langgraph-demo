#!/usr/bin/env bash
set -euo pipefail

readonly PID_FILE="/home/ec2-user/.local/state/product-returns/api/server.pid"

if [[ ! -f "${PID_FILE}" ]]; then
    echo "ReturnFlow API is not managed as a running background process."
    exit 0
fi

api_pid="$(<"${PID_FILE}")"
if [[ ! "${api_pid}" =~ ^[0-9]+$ ]]; then
    echo "Invalid ReturnFlow API PID file; refusing to signal a process." >&2
    exit 1
fi

if kill -0 "${api_pid}" 2>/dev/null; then
    kill "${api_pid}"
    for _ in {1..15}; do
        if ! kill -0 "${api_pid}" 2>/dev/null; then
            break
        fi
        sleep 1
    done
fi

rm -f "${PID_FILE}"
echo "ReturnFlow API has stopped."
