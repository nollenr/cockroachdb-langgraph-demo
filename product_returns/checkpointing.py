"""Checkpoint adapters for fenced LangGraph recovery."""

from __future__ import annotations

from typing import Any

from langchain_cockroachdb import CockroachDBSaver


class PinnedResumeCockroachDBSaver(CockroachDBSaver):
    """Load one published checkpoint while preserving normal resume semantics.

    LangGraph deliberately treats a caller-supplied ``checkpoint_id`` as a
    time-travel fork and does not apply pending writes in that mode.  Failed
    parallel supersteps need those pending writes so completed siblings are
    not executed again.  This adapter keeps the ID out of LangGraph's public
    invocation config, while pinning the saver's first unqualified read to the
    application-published checkpoint.  That retains both selective replay and
    the workflow-run fencing guarantee.
    """

    pinned_checkpoint_id: str | None = None

    def pin_resume_checkpoint(self, checkpoint_id: str) -> None:
        if not checkpoint_id:
            raise ValueError("A pinned resume checkpoint ID is required")
        self.pinned_checkpoint_id = checkpoint_id

    def get_tuple(self, config: dict[str, Any]) -> Any:
        configurable = config.get("configurable", {})
        if (
            self.pinned_checkpoint_id is None
            or configurable.get("checkpoint_id") is not None
        ):
            return super().get_tuple(config)

        pinned_config = dict(config)
        pinned_config["configurable"] = {
            **configurable,
            "checkpoint_id": self.pinned_checkpoint_id,
        }
        return super().get_tuple(pinned_config)
