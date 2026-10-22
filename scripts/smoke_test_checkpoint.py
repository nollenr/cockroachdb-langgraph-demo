#!/usr/bin/env python3
"""Verify LangGraph checkpoint read/write access as product_returns_app.

This test compiles and runs a tiny deterministic graph without an LLM. It does
not call CockroachDBSaver.setup(). On success, it deletes its temporary thread.
"""

from __future__ import annotations

import os
import sys
from typing import TypedDict
from urllib.parse import urlparse
from uuid import uuid4

from langchain_cockroachdb import CockroachDBSaver
from langgraph.graph import END, START, StateGraph


EXPECTED_DATABASE = "product_returns"
EXPECTED_RUNTIME_USER = "product_returns_app"


class SmokeState(TypedDict):
    value: int
    marker: str


def increment(state: SmokeState) -> dict[str, int]:
    """A deterministic node that proves state survived graph execution."""
    return {"value": state["value"] + 1}


def app_url() -> str:
    """Return and validate the app URL without displaying its credentials."""
    connection_url = os.environ.get("CRDB_APP_URL")
    if not connection_url:
        raise RuntimeError(
            "CRDB_APP_URL is not set. Source ./keys.sh and then ./config.sh."
        )

    parsed = urlparse(connection_url)
    database = parsed.path.lstrip("/")

    if parsed.scheme not in {"postgresql", "postgres", "cockroachdb"}:
        raise RuntimeError("CRDB_APP_URL has an unsupported database URL scheme.")
    if parsed.username != EXPECTED_RUNTIME_USER:
        raise RuntimeError(
            "CRDB_APP_URL must use the "
            f"{EXPECTED_RUNTIME_USER!r} runtime identity."
        )
    if database != EXPECTED_DATABASE:
        raise RuntimeError(
            f"CRDB_APP_URL must target the {EXPECTED_DATABASE!r} database."
        )
    if not parsed.hostname:
        raise RuntimeError("CRDB_APP_URL does not contain a database hostname.")

    return connection_url


def build_graph() -> StateGraph:
    builder = StateGraph(SmokeState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder


def main() -> int:
    connection_url = app_url()
    thread_id = f"checkpoint-smoke-{uuid4()}"
    marker = f"marker-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}

    print(
        "Testing LangGraph checkpoints in database "
        f"{EXPECTED_DATABASE!r} as {EXPECTED_RUNTIME_USER!r}..."
    )

    with CockroachDBSaver.from_conn_string(connection_url) as checkpointer:
        # Deliberately do not call checkpointer.setup(); runtime users only use
        # checkpoint tables created previously by the deployment identity.
        graph = build_graph().compile(checkpointer=checkpointer)
        result = graph.invoke({"value": 41, "marker": marker}, config)
        snapshot = graph.get_state(config)
        checkpoint_count = sum(1 for _ in checkpointer.list(config, limit=20))

        if result.get("value") != 42 or result.get("marker") != marker:
            raise RuntimeError("Graph result did not contain the expected state.")
        if snapshot.values.get("value") != 42:
            raise RuntimeError("Persisted checkpoint did not contain value 42.")
        if snapshot.values.get("marker") != marker:
            raise RuntimeError("Persisted checkpoint marker did not match.")
        if checkpoint_count < 1:
            raise RuntimeError("No checkpoints were found for the smoke-test thread.")

        checkpointer.delete_thread(thread_id)
        if checkpointer.get_tuple(config) is not None:
            raise RuntimeError("Smoke-test checkpoint cleanup did not complete.")

    print(
        "Checkpoint smoke test succeeded: write, read, list, and cleanup "
        f"completed across {checkpoint_count} checkpoint(s)."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"Checkpoint smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
