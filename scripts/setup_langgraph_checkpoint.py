#!/usr/bin/env python3
"""Create or upgrade LangGraph's package-owned CockroachDB checkpoint tables.

Run this deployment-time command on the AWS host as the database object owner.
Normal application startup must use CRDB_APP_URL and must not call setup().
"""

from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

from langchain_cockroachdb import CockroachDBSaver


EXPECTED_DATABASE = "product_returns"
EXPECTED_OWNER = "ron"


def owner_url() -> str:
    """Return and validate the owner URL without displaying its credentials."""
    connection_url = os.environ.get("CRDB_RON_URL")
    if not connection_url:
        raise RuntimeError(
            "CRDB_RON_URL is not set. Source ./keys.sh and then ./config.sh."
        )

    parsed = urlparse(connection_url)
    database = parsed.path.lstrip("/")

    if parsed.scheme not in {"postgresql", "postgres", "cockroachdb"}:
        raise RuntimeError("CRDB_RON_URL has an unsupported database URL scheme.")
    if parsed.username != EXPECTED_OWNER:
        raise RuntimeError(
            f"CRDB_RON_URL must use the {EXPECTED_OWNER!r} deployment identity."
        )
    if database != EXPECTED_DATABASE:
        raise RuntimeError(
            f"CRDB_RON_URL must target the {EXPECTED_DATABASE!r} database."
        )
    if not parsed.hostname:
        raise RuntimeError("CRDB_RON_URL does not contain a database hostname.")

    return connection_url


def main() -> int:
    connection_url = owner_url()

    print(
        "Creating or upgrading LangGraph checkpoint tables "
        f"in database {EXPECTED_DATABASE!r} as {EXPECTED_OWNER!r}..."
    )
    with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
        checkpointer.setup()

    print("LangGraph checkpoint schema setup completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Setup refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
