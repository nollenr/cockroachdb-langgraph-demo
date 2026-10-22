"""Render read-only, run-specific CockroachDB inspection SQL."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID


_TEMPLATE = Path(__file__).resolve().parents[1] / "sql" / "inspect_returnflow_run.sql"


def render_run_inspection_sql(run_id: UUID) -> str:
    template = _TEMPLATE.read_text(encoding="utf-8")
    return template.replace("__RUN_ID__", str(run_id))
