"""Shared metrics, tracing, and structured node-event instrumentation."""

from __future__ import annotations

import json
import logging
import os
import hashlib
from pathlib import Path
from collections.abc import Callable, Mapping, Sequence
from functools import wraps
from time import perf_counter
from typing import Any, Protocol
from uuid import UUID

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.context import Context
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
    TraceState,
    set_span_in_context,
)
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

from product_returns.state import ReturnWorkflowState


LOGGER_NAME = "product_returns.graph"
_LOGGER = logging.getLogger(LOGGER_NAME)
_CONFIGURED = False
_TRACER_PROVIDER: TracerProvider | None = None

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "connection_url",
    "database_url",
    "password",
    "private_key",
    "secret",
)

NODE_EXECUTIONS = Counter(
    "product_returns_node_executions",
    "Completed LangGraph node executions.",
    ("node", "status"),
)
NODE_DURATION = Histogram(
    "product_returns_node_duration_seconds",
    "LangGraph node execution duration in seconds.",
    ("node", "status"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
NODE_IN_PROGRESS = Gauge(
    "product_returns_node_in_progress",
    "LangGraph node executions currently in progress.",
    ("node",),
)


class NodeEventRecorder(Protocol):
    """Optional durable projection of node activity for an application UI."""

    def started(self, node_name: str, safe_input: Any) -> UUID: ...

    def succeeded(self, event_id: UUID, safe_output: Any) -> None: ...

    def failed(self, event_id: UUID, error: Exception) -> None: ...


def _normalized_key(value: str) -> str:
    return value.lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_telemetry(value: Any) -> Any:
    """Return a JSON-safe copy with credential-bearing fields redacted."""

    if hasattr(value, "model_dump"):
        return sanitize_telemetry(value.model_dump())
    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if _is_sensitive_key(str(key))
                else sanitize_telemetry(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_telemetry(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _json_text(value: Any) -> str:
    return json.dumps(
        sanitize_telemetry(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _trace_identifiers() -> tuple[str | None, str | None]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return f"{context.trace_id:032x}", f"{context.span_id:016x}"


def _workflow_trace_context(run_id: str) -> Context:
    """Give every node in one durable run the same stable trace identity.

    LangGraph may execute parallel nodes on different threads, where ambient
    context variables are not a reliable correlation mechanism. A SHA-256
    digest of the random workflow UUID supplies a non-secret 128-bit trace ID
    and a stable synthetic parent span ID. The individual node spans still
    receive independent SDK-generated span IDs.
    """

    digest = hashlib.sha256(f"product-returns:{run_id}".encode("utf-8")).digest()
    trace_id = int.from_bytes(digest[:16], "big") or 1
    parent_span_id = int.from_bytes(digest[16:24], "big") or 1
    parent = SpanContext(
        trace_id=trace_id,
        span_id=parent_span_id,
        is_remote=True,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=TraceState(),
    )
    return set_span_in_context(NonRecordingSpan(parent))


class JsonEventFormatter(logging.Formatter):
    """Render one structured JSON object per application log line."""

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _trace_identifiers()
        document: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        if trace_id:
            document["trace_id"] = trace_id
        if span_id:
            document["span_id"] = span_id
        event_data = getattr(record, "event_data", None)
        if event_data is not None:
            document.update(sanitize_telemetry(event_data))
        return json.dumps(document, ensure_ascii=False, sort_keys=True)


def _otlp_traces_endpoint(base_endpoint: str) -> str:
    base = base_endpoint.rstrip("/")
    return base if base.endswith("/v1/traces") else f"{base}/v1/traces"


def configure_observability(
    *,
    service_name: str,
    otlp_enabled: bool,
    otlp_endpoint: str | None = None,
) -> None:
    """Configure JSON events and optional OTLP/HTTP trace export once."""

    global _CONFIGURED, _TRACER_PROVIDER
    if _CONFIGURED:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonEventFormatter())
    _LOGGER.handlers.clear()
    _LOGGER.addHandler(handler)

    log_file = os.environ.get("PRODUCT_RETURNS_LOG_FILE", "").strip()
    if log_file:
        log_path = Path(log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(JsonEventFormatter())
        _LOGGER.addHandler(file_handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": service_name,
                "service.version": "0.1.0",
                "deployment.environment.name": os.environ.get(
                    "DEPLOYMENT_ENVIRONMENT", "demo"
                ),
            }
        )
    )
    if otlp_enabled:
        if not otlp_endpoint:
            raise RuntimeError("OTLP export is enabled but no endpoint is configured")
        exporter = OTLPSpanExporter(endpoint=_otlp_traces_endpoint(otlp_endpoint))
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _TRACER_PROVIDER = provider
    _CONFIGURED = True


def shutdown_observability() -> None:
    """Flush pending spans before a short-lived process exits."""

    if _TRACER_PROVIDER is not None:
        _TRACER_PROVIDER.force_flush()
        _TRACER_PROVIDER.shutdown()


def prometheus_snapshot() -> str:
    """Return the current Prometheus exposition text for tests and diagnostics."""

    return generate_latest().decode("utf-8")


def start_prometheus_metrics_server(port: int) -> None:
    """Expose this process's registry for Prometheus scraping."""

    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid Prometheus metrics port: {port}")
    start_http_server(port, addr="0.0.0.0")


def observable_node(
    node_name: str,
    node: Callable[[ReturnWorkflowState], dict[str, Any]],
    event_recorder: NodeEventRecorder | None = None,
) -> Callable[[ReturnWorkflowState], dict[str, Any]]:
    """Wrap a synchronous LangGraph node with consistent telemetry."""

    @wraps(node)
    def instrumented(state: ReturnWorkflowState) -> dict[str, Any]:
        tracer = trace.get_tracer("product_returns.langgraph")
        safe_input = sanitize_telemetry(state)
        run_id = str(state.get("run_id", "unknown"))
        thread_id = str(state.get("thread_id", "unknown"))
        started = perf_counter()
        status = "failed"
        NODE_IN_PROGRESS.labels(node=node_name).inc()
        node_event_id: UUID | None = None

        try:
            with tracer.start_as_current_span(
                f"langgraph.node.{node_name}",
                context=_workflow_trace_context(run_id),
                attributes={
                    "langgraph.node.name": node_name,
                    "workflow.run_id": run_id,
                    "workflow.thread_id": thread_id,
                },
            ) as span:
                span.add_event("node.input", {"node.input.json": _json_text(safe_input)})
                _LOGGER.info(
                    "node_started",
                    extra={
                        "event_data": {
                            "node": node_name,
                            "run_id": run_id,
                            "thread_id": thread_id,
                            "input": safe_input,
                        }
                    },
                )
                if event_recorder is not None:
                    node_event_id = event_recorder.started(node_name, safe_input)

                try:
                    output = node(state)
                except Exception as error:
                    if event_recorder is not None and node_event_id is not None:
                        event_recorder.failed(node_event_id, error)
                    span.record_exception(error)
                    span.set_status(Status(StatusCode.ERROR, str(error)))
                    _LOGGER.exception(
                        "node_failed",
                        extra={
                            "event_data": {
                                "node": node_name,
                                "run_id": run_id,
                                "thread_id": thread_id,
                                "error_type": type(error).__name__,
                                "error_message": str(error),
                            }
                        },
                    )
                    raise

                safe_output = sanitize_telemetry(output)
                if event_recorder is not None and node_event_id is not None:
                    event_recorder.succeeded(node_event_id, safe_output)
                span.add_event(
                    "node.output",
                    {"node.output_delta.json": _json_text(safe_output)},
                )
                span.set_status(Status(StatusCode.OK))
                status = "succeeded"
                _LOGGER.info(
                    "node_succeeded",
                    extra={
                        "event_data": {
                            "node": node_name,
                            "run_id": run_id,
                            "thread_id": thread_id,
                            "output_delta": safe_output,
                        }
                    },
                )
                return output
        finally:
            duration = perf_counter() - started
            NODE_IN_PROGRESS.labels(node=node_name).dec()
            NODE_EXECUTIONS.labels(node=node_name, status=status).inc()
            NODE_DURATION.labels(node=node_name, status=status).observe(duration)

    return instrumented

