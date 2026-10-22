#!/usr/bin/env python3
"""Print the semantic graph signature without reading any secrets."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.graph_version import (  # noqa: E402
    CURRENT_GRAPH_VERSION,
    graph_signature,
)


print(f"{CURRENT_GRAPH_VERSION} {graph_signature()}")
