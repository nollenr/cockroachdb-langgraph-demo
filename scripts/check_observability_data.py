#!/usr/bin/env python3
"""Verify traces, logs, and the provisioned dashboard without printing data."""

from __future__ import annotations

import base64
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def get_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


tempo_query = urlencode(
    {
        "q": '{ resource.service.name = "product-returns" }',
        "limit": "20",
    }
)
tempo = get_json(f"http://127.0.0.1:3200/api/search?{tempo_query}")
trace_count = len(tempo.get("traces", []))
if trace_count < 1:
    raise RuntimeError("Tempo contains no product-returns traces")

loki_query = urlencode({"query": '{job="product-returns"}', "limit": "100"})
loki = get_json(f"http://127.0.0.1:3100/loki/api/v1/query_range?{loki_query}")
log_count = sum(
    len(stream.get("values", []))
    for stream in loki.get("data", {}).get("result", [])
)
if log_count < 1:
    raise RuntimeError("Loki contains no product-returns log events")

prometheus_query = urlencode(
    {
        "query": (
            "max_over_time(product_returns_node_executions_total{"
            'node="classify_request",status="succeeded"}[30m])'
        )
    }
)
prometheus = get_json(f"http://127.0.0.1:9091/api/v1/query?{prometheus_query}")
prometheus_results = prometheus.get("data", {}).get("result", [])
if not prometheus_results:
    raise RuntimeError(
        "Prometheus contains no retained classifier node execution metric"
    )
node_execution_count = float(prometheus_results[0]["value"][1])
if node_execution_count < 3:
    raise RuntimeError(
        "Prometheus classifier success counter is below the expected value"
    )

evidence_success_query = urlencode(
    {
        "query": (
            "sum(max_over_time(product_returns_node_executions_total{"
            'node=~"lookup_order|retrieve_policy|assess_fraud",'
            'status="succeeded"}[30m]))'
        )
    }
)
evidence_successes = get_json(
    f"http://127.0.0.1:9091/api/v1/query?{evidence_success_query}"
)
evidence_success_results = evidence_successes.get("data", {}).get("result", [])
evidence_success_count = (
    float(evidence_success_results[0]["value"][1])
    if evidence_success_results
    else 0
)
if evidence_success_count < 3:
    raise RuntimeError("Prometheus contains fewer than 3 evidence-node successes")

evidence_failure_query = urlencode(
    {
        "query": (
            "max_over_time(product_returns_node_executions_total{"
            'node="assess_fraud",status="failed"}[30m])'
        )
    }
)
evidence_failures = get_json(
    f"http://127.0.0.1:9091/api/v1/query?{evidence_failure_query}"
)
evidence_failure_results = evidence_failures.get("data", {}).get("result", [])
evidence_failure_count = (
    float(evidence_failure_results[0]["value"][1])
    if evidence_failure_results
    else 0
)
if evidence_failure_count < 1:
    raise RuntimeError("Prometheus does not contain the deliberate fraud failure")

password = os.environ["GRAFANA_ADMIN_PASSWORD"]
token = base64.b64encode(f"admin:{password}".encode()).decode()
dashboards = get_json(
    "http://127.0.0.1:3001/api/search?query=Product%20Returns",
    headers={"Authorization": f"Basic {token}"},
)
dashboard_count = sum(
    1
    for item in dashboards
    if item.get("uid") == "product-returns-graph-operations"
)
if dashboard_count != 1:
    raise RuntimeError("Provisioned Product Returns dashboard was not found")

dashboard = get_json(
    (
        "http://127.0.0.1:3001/api/dashboards/uid/"
        "product-returns-graph-operations"
    ),
    headers={"Authorization": f"Basic {token}"},
)
if "max_over_time" not in json.dumps(dashboard.get("dashboard", {})):
    raise RuntimeError("Grafana has not loaded the batch-compatible metric queries")

print(
    "Observability data verification passed: "
    f"Tempo traces={trace_count}, Loki events={log_count}, "
    f"Prometheus classifier successes={node_execution_count:g}, "
    f"evidence successes={evidence_success_count:g}, "
    f"fraud failures={evidence_failure_count:g}, "
    f"Grafana dashboards={dashboard_count}."
)
