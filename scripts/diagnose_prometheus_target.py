#!/usr/bin/env python3
"""Report the Product Returns Prometheus target state without metric payloads."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import urlopen


def get_json(url: str) -> dict:
    with urlopen(url, timeout=10) as response:
        return json.load(response)


targets = get_json("http://127.0.0.1:9091/api/v1/targets")
matching = [
    target
    for target in targets.get("data", {}).get("activeTargets", [])
    if target.get("labels", {}).get("job") == "product-returns"
]

print(f"Product Returns active target count={len(matching)}")
for target in matching:
    print(f"scrapeUrl={target.get('scrapeUrl')}")
    print(f"health={target.get('health')}")
    print(f"lastScrape={target.get('lastScrape')}")
    print(f"lastError={target.get('lastError')}")

query = urlencode({"query": 'up{job="product-returns"}'})
up = get_json(f"http://127.0.0.1:9091/api/v1/query?{query}")
values = up.get("data", {}).get("result", [])
print(f"Current up-series count={len(values)}")
if values:
    print(f"Current up value={values[0]['value'][1]}")
