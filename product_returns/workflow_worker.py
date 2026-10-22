"""Run one LangGraph turn under a renewable, generation-fenced lease."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from langgraph.types import Command

from product_returns.workflow_runs import (
    LeaseHeartbeat,
    LeaseLostError,
    WorkflowRun,
    langgraph_checkpoint_config,
    publish_checkpoint,
)


class CheckpointStreamingGraph(Protocol):
    """The small compiled-LangGraph surface required by the worker."""

    def stream(
        self,
        input: Any,
        config: Mapping[str, Any],
        *,
        stream_mode: str,
        durability: str,
    ) -> Iterator[Mapping[str, Any]]: ...

    def get_state(self, config: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True)
class GraphTurnResult:
    """The accepted result of one worker-owned graph invocation."""

    run: WorkflowRun
    values: Mapping[str, Any]
    next_nodes: tuple[str, ...]
    checkpoint_id: str
    graph_executed: bool

    @property
    def is_terminal(self) -> bool:
        return not self.next_nodes


def _checkpoint_id(config: Mapping[str, Any]) -> str:
    configurable = config.get("configurable")
    if not isinstance(configurable, Mapping):
        raise RuntimeError("LangGraph checkpoint event has no configurable section")
    checkpoint_id = configurable.get("checkpoint_id")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise RuntimeError("LangGraph checkpoint event has no checkpoint_id")
    return checkpoint_id


def _existing_checkpoint_result(
    graph: CheckpointStreamingGraph,
    lease: WorkflowRun,
) -> GraphTurnResult | None:
    if lease.latest_checkpoint_id is None:
        return None
    snapshot = graph.get_state(langgraph_checkpoint_config(lease))
    next_nodes = tuple(cast(tuple[str, ...], snapshot.next))
    if next_nodes:
        return None
    return GraphTurnResult(
        run=lease,
        values=cast(Mapping[str, Any], snapshot.values),
        next_nodes=(),
        checkpoint_id=lease.latest_checkpoint_id,
        graph_executed=False,
    )


def publish_recovery_checkpoint(
    connection_url: str,
    *,
    graph: CheckpointStreamingGraph,
    lease: WorkflowRun,
    round_name: str,
) -> GraphTurnResult:
    """Fence and publish the latest saver state after a controlled node failure.

    Reading the thread's unqualified latest checkpoint is safe here because the
    same worker still owns a live lease, and publication remains fenced by that
    exact lease generation and state version.
    """

    snapshot = graph.get_state({"configurable": {"thread_id": lease.thread_id}})
    checkpoint_id = _checkpoint_id(snapshot.config)
    next_nodes = tuple(str(node) for node in snapshot.next)
    published = publish_checkpoint(
        connection_url,
        run_id=lease.run_id,
        worker_id=cast(str, lease.lease_owner),
        lease_generation=lease.lease_generation,
        expected_state_version=lease.state_version,
        checkpoint_id=checkpoint_id,
        current_round=round_name,
        next_nodes=next_nodes,
    )
    if published is None:
        raise LeaseLostError(
            "Worker lost its lease before publishing the recovery checkpoint "
            f"{checkpoint_id} for run {lease.run_id}"
        )
    return GraphTurnResult(
        run=published,
        values=cast(Mapping[str, Any], snapshot.values),
        next_nodes=next_nodes,
        checkpoint_id=checkpoint_id,
        graph_executed=True,
    )


def execute_graph_turn(
    connection_url: str,
    *,
    graph: CheckpointStreamingGraph,
    lease: WorkflowRun,
    initial_state: Mapping[str, Any] | None,
    round_name: str,
    heartbeat_interval_seconds: float,
    lease_seconds: int,
    resume_value: Mapping[str, Any] | None = None,
    apply_pending_writes: bool = False,
) -> GraphTurnResult:
    """Execute and publish exactly one durable graph turn.

    Checkpoint streaming captures IDs created by this invocation. We never ask
    LangGraph for the thread's unqualified latest checkpoint after execution,
    so a stale worker's orphan checkpoint cannot be accidentally published.
    """

    if lease.latest_checkpoint_id is None and initial_state is None:
        raise ValueError("A new workflow requires initial_state")
    if lease.latest_checkpoint_id is not None and initial_state is not None:
        raise ValueError("A resumed workflow must use checkpoint state, not new input")
    if lease.latest_checkpoint_id is None and resume_value is not None:
        raise ValueError("A new workflow cannot carry an interrupt resume value")

    graph_input: Any = (
        Command(resume=dict(resume_value))
        if resume_value is not None
        else initial_state
    )

    config = langgraph_checkpoint_config(lease)
    if apply_pending_writes:
        # An explicit checkpoint_id means "fork from history" to LangGraph,
        # which intentionally ignores pending writes.  The recovery saver pins
        # its database read internally, so omit the public ID here and retain
        # ordinary failed-superstep resume semantics.
        config["configurable"].pop("checkpoint_id", None)
    with LeaseHeartbeat(
        connection_url,
        lease,
        interval_seconds=heartbeat_interval_seconds,
        lease_seconds=lease_seconds,
    ) as heartbeat:
        existing = _existing_checkpoint_result(graph, lease)
        if existing is not None:
            return existing

        last_checkpoint: Mapping[str, Any] | None = None
        for checkpoint in graph.stream(
            graph_input,
            config,
            stream_mode="checkpoints",
            durability="sync",
        ):
            heartbeat.raise_if_lost()
            last_checkpoint = checkpoint

        heartbeat.raise_if_lost()
        if last_checkpoint is None:
            raise RuntimeError("LangGraph completed without emitting a checkpoint")

        checkpoint_config = last_checkpoint.get("config")
        if not isinstance(checkpoint_config, Mapping):
            raise RuntimeError("LangGraph checkpoint event has no config")
        checkpoint_id = _checkpoint_id(checkpoint_config)

        values = last_checkpoint.get("values")
        if not isinstance(values, Mapping):
            raise RuntimeError("LangGraph checkpoint event has no state values")
        raw_next = last_checkpoint.get("next", ())
        if not isinstance(raw_next, (tuple, list)):
            raise RuntimeError("LangGraph checkpoint event has invalid next nodes")
        next_nodes = tuple(str(node) for node in raw_next)

        published = publish_checkpoint(
            connection_url,
            run_id=lease.run_id,
            worker_id=cast(str, lease.lease_owner),
            lease_generation=lease.lease_generation,
            expected_state_version=lease.state_version,
            checkpoint_id=checkpoint_id,
            current_round=round_name,
            next_nodes=next_nodes,
        )
        if published is None:
            raise LeaseLostError(
                "Worker lost its lease or state-version race before publishing "
                f"checkpoint {checkpoint_id} for run {lease.run_id}"
            )

        return GraphTurnResult(
            run=published,
            values=values,
            next_nodes=next_nodes,
            checkpoint_id=checkpoint_id,
            graph_executed=True,
        )

