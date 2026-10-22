#!/usr/bin/env bash
set -euo pipefail

LOG_FILE='/home/ec2-user/.local/state/product-returns/logs/events.jsonl'

test -s "$LOG_FILE"
line_count=$(wc -l < "$LOG_FILE")

echo "Structured observability log exists and contains ${line_count} event lines."
