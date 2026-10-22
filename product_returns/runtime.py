"""Reusable graph runtime and recovery-capable ReturnFlow dispatcher."""

from __future__ import annotations

import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from time import sleep
from typing import Any, cast
from uuid import UUID, uuid4

from langchain_cockroachdb import (
    CockroachDBEngine,
    CockroachDBSaver,
    CockroachDBVectorStore,
)
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langgraph.types import RetryPolicy

from product_returns.approval_store import (
    commit_approval_resolution,
    load_manager_resume_value,
)
from product_returns.checkpointing import PinnedResumeCockroachDBSaver
from product_returns.decision_store import commit_return_decision
from product_returns.demo_api_store import (
    commit_non_refund_classification,
    list_claimable_run_ids,
    load_initial_state,
)
from product_returns.evidence import (
    create_fraud_assessment_node,
    create_order_lookup_node,
    create_policy_retrieval_node,
    retryable_evidence_error,
)
from product_returns.failure_injection import (
    InjectedDemoFailure,
    inject_failure_once,
    inject_payment_failure_once,
    pause_for_injected_failure,
    record_recovery_worker_claim,
)
from product_returns.graph import build_evidence_graph
from product_returns.node_events import CockroachNodeEventRecorder
from product_returns.observability import (
    configure_observability,
    start_prometheus_metrics_server,
)
from product_returns.refund import create_issue_refund_node, retryable_refund_error
from product_returns.refund_store import commit_refund_completion
from product_returns.reservation import (
    create_reserve_return_items_node,
    retryable_reservation_error,
)
from product_returns.reservation_store import commit_reservation_conflict
from product_returns.state import (
    ClassificationResult,
    ManagerDecision,
    RefundResult,
    ReturnDecision,
    ReturnReservationResult,
)
from product_returns.workflow_runs import (
    WorkflowRun,
    claim_workflow_run,
    release_workflow_run,
)
from product_returns.workflow_worker import (
    execute_graph_turn,
    publish_recovery_checkpoint,
)


_LOGGER = logging.getLogger("product_returns.api")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


class ReturnWorkflowRuntime:
    """Own shared model/vector objects and execute one fenced workflow turn."""

    def __init__(self, connection_url: str) -> None:
        self.connection_url = connection_url
        model_name = _required("OPENAI_CLASSIFIER_MODEL")
        reasoning_effort = _required("OPENAI_CLASSIFIER_REASONING_EFFORT")
        embedding_model = _required("OPENAI_EMBEDDING_MODEL")
        dimensions = int(_required("OPENAI_EMBEDDING_DIMENSIONS"))
        namespace = _required("POLICY_VECTOR_NAMESPACE")

        configure_observability(
            service_name=_required("OTEL_SERVICE_NAME"),
            otlp_enabled=_required("PRODUCT_RETURNS_OTLP_ENABLED").lower() == "true",
            otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
        )
        start_prometheus_metrics_server(int(_required("PROMETHEUS_METRICS_PORT")))

        engine = CockroachDBEngine.from_connection_string(connection_url)
        vector_store = CockroachDBVectorStore(
            engine=engine,
            embeddings=OpenAIEmbeddings(model=embedding_model, dimensions=dimensions),
            collection_name=_required("POLICY_VECTOR_TABLE"),
            namespace=namespace,
        )
        recorder = CockroachNodeEventRecorder(connection_url)
        order_lookup_node = create_order_lookup_node(connection_url)
        policy_retrieval_node = create_policy_retrieval_node(
            connection_url,
            vector_store,
            namespace,
            embedding_model,
            dimensions,
        )
        fraud_assessment_node = create_fraud_assessment_node(connection_url)
        self._graph_builder = build_evidence_graph(
            ChatOpenAI(model=model_name, reasoning_effort=reasoning_effort),
            model_name,
            reasoning_effort,
            order_lookup_node=inject_failure_once(
                connection_url,
                "lookup_order",
                order_lookup_node,
            ),
            policy_retrieval_node=inject_failure_once(
                connection_url,
                "retrieve_policy",
                policy_retrieval_node,
            ),
            fraud_assessment_node=inject_failure_once(
                connection_url,
                "assess_fraud",
                fraud_assessment_node,
            ),
            evidence_retry_policy=RetryPolicy(
                initial_interval=0.25,
                backoff_factor=2.0,
                max_interval=2.0,
                max_attempts=3,
                jitter=True,
                retry_on=retryable_evidence_error,
            ),
            reservation_node=create_reserve_return_items_node(connection_url),
            reservation_retry_policy=RetryPolicy(
                initial_interval=0.1,
                backoff_factor=2.0,
                max_interval=1.0,
                max_attempts=3,
                jitter=True,
                retry_on=retryable_reservation_error,
            ),
            refund_node=create_issue_refund_node(
                connection_url,
                after_provider_hook=lambda prepared, provider: inject_payment_failure_once(
                    connection_url, prepared, provider
                ),
            ),
            refund_retry_policy=RetryPolicy(
                initial_interval=0.1,
                backoff_factor=2.0,
                max_interval=1.0,
                max_attempts=3,
                jitter=True,
                retry_on=retryable_refund_error,
            ),
            node_event_recorder=recorder,
        )
        self._lease_seconds = int(_required("WORKFLOW_LEASE_DURATION_SECONDS"))
        self._heartbeat_seconds = float(
            _required("WORKFLOW_HEARTBEAT_INTERVAL_SECONDS")
        )

    def process_run(self, run_id: UUID, worker_id: str) -> bool:
        """Claim and advance one run to its next durable business boundary."""

        lease = claim_workflow_run(
            self.connection_url,
            run_id=run_id,
            worker_id=worker_id,
            lease_seconds=self._lease_seconds,
        )
        if lease is None:
            return False

        if lease.current_round == "recovery_resume_requested":
            record_recovery_worker_claim(self.connection_url, lease=lease)

        try:
            initial_state: dict[str, str] | None = None
            resume_value: ManagerDecision | None = None
            if lease.latest_checkpoint_id is None:
                initial_state = load_initial_state(self.connection_url, run_id)
                round_name = "return_decision"
            elif lease.current_round == "approval_resume":
                resume_value = load_manager_resume_value(
                    self.connection_url,
                    run_id=run_id,
                )
                round_name = "approval_resume"
            else:
                round_name = "recovery_resume"

            is_failure_recovery = lease.current_round == "recovery_resume_requested"
            saver_type = (
                PinnedResumeCockroachDBSaver
                if is_failure_recovery
                else CockroachDBSaver
            )
            with saver_type.from_conn_string(self.connection_url) as saver:
                if is_failure_recovery:
                    if lease.latest_checkpoint_id is None:
                        raise RuntimeError("Recovery run has no published checkpoint")
                    saver.pin_resume_checkpoint(lease.latest_checkpoint_id)
                graph = self._graph_builder.compile(checkpointer=saver)
                turn = execute_graph_turn(
                    self.connection_url,
                    graph=graph,
                    lease=lease,
                    initial_state=initial_state,
                    resume_value=resume_value,
                    round_name=round_name,
                    heartbeat_interval_seconds=self._heartbeat_seconds,
                    lease_seconds=self._lease_seconds,
                    apply_pending_writes=is_failure_recovery,
                )

            self._commit_turn(turn.run, turn.checkpoint_id, turn.values, turn.next_nodes)
            return True
        except InjectedDemoFailure as error:
            _LOGGER.warning(
                "Workflow run %s paused after injected failure at %s",
                run_id,
                error.node_name,
            )
            with CockroachDBSaver.from_conn_string(self.connection_url) as saver:
                recovery_graph = self._graph_builder.compile(checkpointer=saver)
                recovery = publish_recovery_checkpoint(
                    self.connection_url,
                    graph=recovery_graph,
                    lease=lease,
                    round_name="recovery_paused",
                )
            pause_for_injected_failure(
                self.connection_url,
                lease=lease,
                published=recovery.run,
                checkpoint_id=recovery.checkpoint_id,
                failure=error,
            )
            return False
        except Exception:
            _LOGGER.exception("Workflow run %s failed in worker %s", run_id, worker_id)
            retry_at = datetime.now(timezone.utc) + timedelta(seconds=3)
            release_workflow_run(
                self.connection_url,
                run_id=lease.run_id,
                worker_id=cast(str, lease.lease_owner),
                lease_generation=lease.lease_generation,
                new_status="retry_wait",
                next_attempt_at=retry_at,
            )
            return False

    def _commit_turn(
        self,
        lease: WorkflowRun,
        checkpoint_id: str,
        values: Any,
        next_nodes: tuple[str, ...],
    ) -> None:
        decision = cast(ReturnDecision | None, values.get("decision"))
        classification = cast(ClassificationResult | None, values.get("classification"))
        reservation = cast(
            ReturnReservationResult | None,
            values.get("return_reservation"),
        )
        refund = cast(RefundResult | None, values.get("refund_result"))
        manager = cast(ManagerDecision | None, values.get("manager_decision"))

        if next_nodes == ("await_manager_approval",):
            if decision is None:
                raise RuntimeError("Approval checkpoint has no return decision")
            commit_return_decision(
                self.connection_url,
                lease=lease,
                decision=decision,
                checkpoint_id=checkpoint_id,
            )
            return
        if refund is not None:
            if decision is None:
                raise RuntimeError("Refund checkpoint has no return decision")
            commit_refund_completion(
                self.connection_url,
                lease=lease,
                refund_result=refund,
                decision=decision,
                checkpoint_id=checkpoint_id,
            )
            return
        if reservation is not None and reservation["status"] == "conflict":
            commit_reservation_conflict(
                self.connection_url,
                lease=lease,
                reservation=reservation,
                checkpoint_id=checkpoint_id,
            )
            return
        if manager is not None and manager["decision"] == "rejected":
            commit_approval_resolution(
                self.connection_url,
                lease=lease,
                manager_decision=manager,
                checkpoint_id=checkpoint_id,
            )
            return
        if decision is not None:
            commit_return_decision(
                self.connection_url,
                lease=lease,
                decision=decision,
                checkpoint_id=checkpoint_id,
            )
            return
        if classification is not None and classification["intent"] != "refund":
            commit_non_refund_classification(
                self.connection_url,
                lease=lease,
                classification=classification,
                checkpoint_id=checkpoint_id,
            )
            return
        raise RuntimeError("Graph turn reached no recognized durable boundary")


class WorkflowDispatcher:
    """Continuously reclaim due runs; CockroachDB remains the source of truth."""

    def __init__(self, runtime: ReturnWorkflowRuntime, poll_seconds: float = 0.5) -> None:
        self._runtime = runtime
        self._poll_seconds = poll_seconds
        self._stop = Event()
        self._worker_id = f"api-{socket.gethostname()}-{os.getpid()}-{uuid4()}"
        self._thread = Thread(target=self._run, name="returnflow-dispatcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                run_ids = list_claimable_run_ids(self._runtime.connection_url)
                if not run_ids:
                    self._stop.wait(self._poll_seconds)
                    continue
                for run_id in run_ids:
                    if self._stop.is_set():
                        return
                    self._runtime.process_run(run_id, self._worker_id)
            except Exception:
                _LOGGER.exception("ReturnFlow dispatcher iteration failed")
                sleep(min(2.0, self._poll_seconds * 4))
