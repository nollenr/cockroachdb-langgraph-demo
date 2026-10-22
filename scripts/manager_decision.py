#!/usr/bin/env python3
"""Record a manager's approve/reject response for a paused return workflow."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from uuid import UUID


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.approval_store import record_manager_decision  # noqa: E402


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", type=UUID)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--approve", action="store_true")
    choice.add_argument("--reject", action="store_true")
    parser.add_argument("--manager", required=True)
    parser.add_argument("--note")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    connection_url = os.environ.get("CRDB_APP_URL")
    if not connection_url:
        raise RuntimeError("CRDB_APP_URL is not set")
    result = record_manager_decision(
        connection_url,
        run_id=args.run_id,
        decision="approved" if args.approve else "rejected",
        decided_by=args.manager,
        decision_note=args.note,
    )
    print(
        f"Manager decision recorded for run {result.run_id}; "
        "the workflow is ready to resume from its published checkpoint."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
