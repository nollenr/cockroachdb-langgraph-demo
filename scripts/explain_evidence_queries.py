#!/usr/bin/env python3
"""EXPLAIN every relational query introduced by the evidence round."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.evidence import (  # noqa: E402
    AUTHORITATIVE_POLICY_SQL,
    FRAUD_ASSESSMENT_SQL,
    ORDER_LOOKUP_SQL,
)


def main() -> int:
    connection_url = os.environ.get("CRDB_APP_URL")
    if not connection_url:
        raise RuntimeError("CRDB_APP_URL is not set")

    statements = (
        ("order lookup", ORDER_LOOKUP_SQL, ("CUST-RON", "DEMO-1001")),
        (
            "authoritative policy verification",
            AUTHORITATIVE_POLICY_SQL,
            ("standard-returns", "1.0"),
        ),
        ("fraud assessment", FRAUD_ASSESSMENT_SQL, ("CUST-BOB",)),
    )
    with psycopg.connect(connection_url) as connection:
        for name, statement, parameters in statements:
            rows = connection.execute(
                f"EXPLAIN (OPT, VERBOSE) {statement}",
                parameters,
            ).fetchall()
            if not rows:
                raise RuntimeError(f"EXPLAIN returned no plan for {name}")
            print(f"--- {name} ---")
            for row in rows:
                print(row[0])

    print("Evidence-query EXPLAIN completed successfully for all 3 queries.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Evidence-query EXPLAIN failed: {error}", file=sys.stderr)
        raise
