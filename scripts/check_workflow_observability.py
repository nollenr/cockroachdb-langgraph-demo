#!/usr/bin/env python3
"""Verify one recent workflow is correlated across metrics, logs, and traces."""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


NODES = {
    "classify_request",
    "lookup_order",
    "retrieve_policy",
    "assess_fraud",
    "decide_return",
}


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def recent_decision_event() -> dict:
    query = '{job="product-returns"} | json | node="decide_return" | event="node_succeeded"'
    document = get_json(
        "http://127.0.0.1:3100/loki/api/v1/query_range?"
        + urlencode({"query": query, "limit": "20", "direction": "backward"})
    )
    events: list[tuple[int, dict]] = []
    for stream in document.get("data", {}).get("result", []):
        for timestamp, line in stream.get("values", []):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("run_id") and event.get("trace_id"):
                events.append((int(timestamp), event))
    if not events:
        raise RuntimeError("Loki has no recent correlated decide_return event")
    return max(events, key=lambda item: item[0])[1]


def tempo_span_names(trace_id: str) -> set[str]:
    document = get_json(f"http://127.0.0.1:3200/api/traces/{quote(trace_id)}")
    names: set[str] = set()
    for resource_spans in document.get("batches", document.get("resourceSpans", [])):
        scopes = resource_spans.get(
            "instrumentationLibrarySpans",
            resource_spans.get("scopeSpans", []),
        )
        for scope in scopes:
            for span in scope.get("spans", []):
                name = span.get("name") or span.get("operationName")
                if name:
                    names.add(str(name))
    return names


def prometheus_nodes() -> set[str]:
    expression = (
        "max_over_time(product_returns_node_executions_total{"
        'status="succeeded"}[30m])'
    )
    document = get_json(
        "http://127.0.0.1:9091/api/v1/query?"
        + urlencode({"query": expression})
    )
    return {
        str(result.get("metric", {}).get("node"))
        for result in document.get("data", {}).get("result", [])
        if float(result.get("value", [0, 0])[1]) >= 1
    }


def main() -> int:
    event = recent_decision_event()
    run_id = str(event["run_id"])
    trace_id = str(event["trace_id"])

    span_names = tempo_span_names(trace_id)
    expected_span_names = {f"langgraph.node.{node}" for node in NODES}
    missing_spans = expected_span_names - span_names
    if missing_spans:
        raise RuntimeError(
            "Tempo trace is missing workflow spans: " + ", ".join(sorted(missing_spans))
        )

    metric_nodes = prometheus_nodes()
    missing_metrics = NODES - metric_nodes
    if missing_metrics:
        raise RuntimeError(
            "Prometheus is missing workflow nodes: " + ", ".join(sorted(missing_metrics))
        )

    password = os.environ["GRAFANA_ADMIN_PASSWORD"]
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    dashboard = get_json(
        "http://127.0.0.1:3001/api/dashboards/uid/product-returns-graph-operations",
        headers={"Authorization": f"Basic {token}"},
    )
    if dashboard.get("dashboard", {}).get("uid") != "product-returns-graph-operations":
        raise RuntimeError("Grafana Product Returns dashboard was not found")

    print(
        "Workflow observability verified: "
        f"run_id={run_id}, trace_id={trace_id}, "
        f"Tempo node spans={len(expected_span_names)}, "
        f"Prometheus nodes={len(NODES)}, Loki decision event=1, Grafana dashboard=1."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
