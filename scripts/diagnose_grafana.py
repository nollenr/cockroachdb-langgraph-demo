#!/usr/bin/env python3
"""Check Grafana provisioning through its API without exposing credentials."""

from __future__ import annotations

import base64
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


password = os.environ["GRAFANA_ADMIN_PASSWORD"]
token = base64.b64encode(f"admin:{password}".encode()).decode()
headers = {"Authorization": f"Basic {token}"}


def request_json(path: str) -> tuple[int, object | None]:
    request = Request(f"http://127.0.0.1:3001{path}", headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, None


status, search = request_json("/api/search?query=Product%20Returns")
print(f"Grafana search API status={status}")
if isinstance(search, list):
    print(f"Grafana matching dashboard count={len(search)}")
    for item in search:
        print(f"dashboard uid={item.get('uid')} title={item.get('title')}")

status, _ = request_json(
    "/api/dashboards/uid/product-returns-graph-operations"
)
print(f"Expected dashboard UID lookup status={status}")
