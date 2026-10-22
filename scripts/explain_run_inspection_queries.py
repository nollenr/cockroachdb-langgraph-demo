#!/usr/bin/env python3
"""EXPLAIN every statement in the run-specific CockroachDB inspection pack."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

import psycopg


REPO_DIR = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_DIR / "sql" / "inspect_returnflow_run.sql"
EXPLAIN_RUN_ID = UUID("00000000-0000-4000-8000-000000000000")


def main() -> int:
    connection_url = os.environ["CRDB_APP_URL"]
    sql = TEMPLATE.read_text(encoding="utf-8").replace(
        "__RUN_ID__", str(EXPLAIN_RUN_ID)
    )
    executable_sql = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [
        statement.strip()
        for statement in executable_sql.split(";")
        if statement.strip()
    ]
    with psycopg.connect(connection_url, autocommit=True) as connection:
        for index, statement in enumerate(statements, start=1):
            rows = connection.execute(f"EXPLAIN {statement}").fetchall()
            plan = "\n".join(str(row[0]) for row in rows)
            print(f"QUERY {index} PLAN\n{plan}\n")
    print(f"PASS: EXPLAIN succeeded for all {len(statements)} inspection queries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
