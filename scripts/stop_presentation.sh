#!/usr/bin/env bash
set -euo pipefail

readonly STATE_DIR="/home/ec2-user/.local/state/product-returns/presentation"
readonly PID_FILE="${STATE_DIR}/server.pid"

if [[ ! -f "${PID_FILE}" ]]; then
    echo "ReturnFlow is not managed as a running background process."
    exit 0
fi

presentation_pid="$(<"${PID_FILE}")"
if [[ ! "${presentation_pid}" =~ ^[0-9]+$ ]]; then
    echo "Invalid ReturnFlow PID file; refusing to signal a process." >&2
    exit 1
fi

if kill -0 "${presentation_pid}" 2>/dev/null; then
    kill "${presentation_pid}"
    for _ in {1..10}; do
        if ! kill -0 "${presentation_pid}" 2>/dev/null; then
            break
        fi
        sleep 1
    done
fi

rm -f "${PID_FILE}"
echo "ReturnFlow has stopped."
