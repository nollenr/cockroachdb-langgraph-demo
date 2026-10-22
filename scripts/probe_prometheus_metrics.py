#!/usr/bin/env python3
"""Expose a short-lived probe metric for scrape-path diagnostics."""

from time import sleep

from prometheus_client import Gauge, start_http_server


PROBE = Gauge(
    "product_returns_observability_probe",
    "Temporary metric used to verify Docker-to-host scraping.",
)
PROBE.set(1)
start_http_server(8000, addr="0.0.0.0")
print("Prometheus probe is available on port 8000 for 30 seconds.", flush=True)
sleep(30)
