"""Source-controlled identity for the durable Product Returns graph."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Final


# This is the authoritative version stored on every newly created workflow run.
# Bump it only with an explicit compatibility decision for in-flight runs.
CURRENT_GRAPH_VERSION: Final = "8"

# Keep this manifest semantic: topology, routing, state, and node contracts
# belong here; logging, comments, and other operational-only changes do not.
GRAPH_MANIFEST: Final = {
    "state_schema_version": "8",
    "nodes": {
        "classify_request": "3",
        "lookup_order": "2",
        "retrieve_policy": "2",
        "assess_fraud": "2",
        "decide_return": "3",
        "reserve_return_items": "1",
        "await_manager_approval": "1",
        "issue_refund": "1",
    },
    "routes": {
        "start": ["classify_request"],
        "refund": ["lookup_order", "retrieve_policy", "assess_fraud"],
        "non_refund": ["end"],
        "lookup_order": ["decide_return"],
        "retrieve_policy": ["decide_return"],
        "assess_fraud": ["decide_return"],
        "decide_return": ["end", "reserve_return_items"],
        "reserve_return_items": ["end", "await_manager_approval", "issue_refund"],
        "await_manager_approval": ["end", "issue_refund"],
        "issue_refund": ["end"],
    },
}

# A manifest change without an intentional version bump must fail validation.
EXPECTED_GRAPH_SIGNATURES: Final = {
    "1": "bc69451c517d48e526693ef0ff12f04ec1cb653bdea867ca31fae28787465890",
    "2": "6513564bf49d803a07c1599ab8cacf093457ae8510a1424ef43a20931dca5c4f",
    "3": "9795702b25b98353f27a23ad4bc77fbd267637a8547cd1fe9226d2b04eb7afc0",
    "4": "485c596d12490a4bb18d66a443856c3793459ce1ad36d319899afcbbc5752b00",
    "5": "31d5fc1a0e63767c31c790853c25e7d2042031f693922ae21d56d28b5a30c1d3",
    "6": "bb98109d3596db4f6d741bfe2ab408f4009da7dce8b3481d6a92874888ded517",
    "7": "c49fd5f0e11aeec2ddcea2f3c1a1dfcf2240a14a8cfe54f4cf0986a76bd197f7",
    "8": "e240654ef34d45fe3fc0f0b2f95cc9b3c4276411a8e90fddcc9985526115204e",
}


def graph_signature() -> str:
    """Return a deterministic SHA-256 signature for the semantic manifest."""

    canonical = json.dumps(
        GRAPH_MANIFEST,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_graph_definition() -> None:
    """Fail if topology/contracts changed without registering the version."""

    expected = EXPECTED_GRAPH_SIGNATURES.get(CURRENT_GRAPH_VERSION)
    actual = graph_signature()
    if expected is None:
        raise RuntimeError(
            f"Graph version {CURRENT_GRAPH_VERSION!r} has no registered signature"
        )
    if actual != expected:
        raise RuntimeError(
            "Graph definition changed without a matching version/signature update: "
            f"version={CURRENT_GRAPH_VERSION!r}, expected={expected}, actual={actual}"
        )


def validate_deployment_graph_version() -> None:
    """Treat deployment configuration as an assertion, never as authority."""

    expected = os.environ.get("EXPECTED_GRAPH_VERSION")
    if expected and expected != CURRENT_GRAPH_VERSION:
        raise RuntimeError(
            "Deployed graph-version assertion does not match the source code: "
            f"expected={expected!r}, source={CURRENT_GRAPH_VERSION!r}"
        )

