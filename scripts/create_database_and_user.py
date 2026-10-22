#!/usr/bin/env python3
"""Create the fresh demo database and login without exposing credentials."""

from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlparse

import psycopg
from psycopg import sql


DATABASE = "product_returns"
APP_USER = "product_returns_app"


def main() -> int:
    owner_url = os.environ.get("CRDB_RON_ADMIN_URL", "")
    app_password = os.environ.get("CRDB_APP_PASSWORD", "")
    parsed = urlparse(owner_url)
    if parsed.username != "ron" or parsed.path != "/defaultdb" or not parsed.hostname:
        raise RuntimeError("Owner connection must target defaultdb as ron.")
    if not app_password:
        raise RuntimeError("CRDB_APP_PASSWORD is missing.")

    with psycopg.connect(owner_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            users = {row[0] for row in cursor.execute("SHOW USERS")}
            if APP_USER in users:
                print(f"SQL user {APP_USER} already exists; password left unchanged.")
            else:
                cursor.execute(
                    sql.SQL("CREATE USER {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(APP_USER), sql.Literal(app_password)
                    )
                )
                print(f"Created SQL user {APP_USER}.")

            databases = {row[0] for row in cursor.execute("SHOW DATABASES")}
            if DATABASE in databases:
                print(f"Database {DATABASE} already exists; left unchanged.")
            else:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE))
                )
                print(f"Created database {DATABASE}.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, psycopg.Error) as exc:
        # Connection and SQL exceptions may contain credential-bearing URLs.
        print(f"Database setup failed ({type(exc).__name__}).", file=sys.stderr)
        if isinstance(exc, psycopg.Error):
            message = str(exc).lower()
            categories = {
                "authentication": r"password authentication|invalid password|28p01",
                "TLS": r"certificate|ssl|tls|x509",
                "network": r"timeout|connection refused|allowlist|not allowed",
                "DNS": r"could not translate host|no such host|name or service not known",
                "connection syntax": r"invalid connection option|invalid uri|invalid dsn|percent",
                "cluster routing": r"cluster not found|cluster id|cluster name",
            }
            category = next(
                (name for name, pattern in categories.items() if re.search(pattern, message)),
                "other",
            )
            print(f"Category: {category}; SQLSTATE: {exc.sqlstate or 'none'}.", file=sys.stderr)
        raise SystemExit(1) from None
