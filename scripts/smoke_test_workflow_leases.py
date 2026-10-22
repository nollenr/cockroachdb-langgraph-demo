#!/usr/bin/env python3
"""Prove run claiming, heartbeat, reclaim, and stale-worker fencing."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from time import sleep
from urllib.parse import urlparse
from uuid import uuid4

import psycopg


REPO_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_DIR))

from product_returns.graph_version import (  # noqa: E402
    CURRENT_GRAPH_VERSION,
    validate_deployment_graph_version,
    validate_graph_definition,
)
from product_returns.workflow_runs import (  # noqa: E402
    LeaseHeartbeat,
    claim_workflow_run,
    create_workflow_run,
    get_workflow_run,
    publish_checkpoint,
    release_workflow_run,
    renew_workflow_lease,
)


EXPECTED_DATABASE = "product_returns"
EXPECTED_RUNTIME_USER = "product_returns_app"
CUSTOMER_ID = "10000000-0000-4000-8000-000000000001"
ORDER_ID = "30000000-0000-4000-8000-000000000001"


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def validated_app_url() -> str:
    connection_url = required_environment("CRDB_APP_URL")
    parsed = urlparse(connection_url)
    if parsed.username != EXPECTED_RUNTIME_USER:
        raise RuntimeError(
            f"CRDB_APP_URL must use {EXPECTED_RUNTIME_USER!r}, not an owner identity"
        )
    if parsed.path.lstrip("/") != EXPECTED_DATABASE:
        raise RuntimeError(f"CRDB_APP_URL must target {EXPECTED_DATABASE!r}")
    return connection_url


def main() -> int:
    connection_url = validated_app_url()
    validate_deployment_graph_version()
    validate_graph_definition()

    lease_seconds = 2
    heartbeat_interval = 0.4
    run_id = uuid4()
    missing_version_run_id = uuid4()
    return_request_id = uuid4()
    thread_id = f"lease-smoke-{uuid4()}"

    with psycopg.connect(connection_url, autocommit=True) as connection:
        connection.execute(
            """
            INSERT INTO return_requests (
                return_request_id,
                customer_id,
                order_id,
                request_text
            ) VALUES (%s, %s, %s, %s)
            """,
            (
                return_request_id,
                CUSTOMER_ID,
                ORDER_ID,
                "Temporary workflow-lease smoke-test request.",
            ),
        )

    try:
        try:
            with psycopg.connect(connection_url, autocommit=True) as connection:
                connection.execute(
                    """
                    INSERT INTO workflow_runs (
                        run_id,
                        return_request_id,
                        thread_id
                    ) VALUES (%s, %s, %s)
                    """,
                    (
                        missing_version_run_id,
                        return_request_id,
                        f"missing-version-{uuid4()}",
                    ),
                )
        except psycopg.errors.NotNullViolation:
            print("PASS graph version: omission is rejected; no database default exists.")
        else:
            raise RuntimeError("A workflow run was inserted without graph_version")

        created = create_workflow_run(
            connection_url,
            return_request_id=return_request_id,
            thread_id=thread_id,
            run_id=run_id,
        )
        if created.graph_version != CURRENT_GRAPH_VERSION:
            raise RuntimeError("New run did not use the source-controlled graph version")

        worker_a = f"worker-a-{uuid4()}"
        first_lease = claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=worker_a,
            lease_seconds=lease_seconds,
        )
        if first_lease is None or first_lease.lease_generation != 1:
            raise RuntimeError("Worker A did not receive lease generation 1")
        if (
            claim_workflow_run(
                connection_url,
                run_id=run_id,
                worker_id="competing-worker",
                lease_seconds=lease_seconds,
            )
            is not None
        ):
            raise RuntimeError("A competing worker claimed an unexpired lease")

        first_checkpoint = publish_checkpoint(
            connection_url,
            run_id=run_id,
            worker_id=worker_a,
            lease_generation=first_lease.lease_generation,
            expected_state_version=0,
            checkpoint_id="checkpoint-generation-1",
            current_round="evidence",
            next_nodes=("lookup_order", "retrieve_policy", "assess_fraud"),
        )
        if first_checkpoint is None or first_checkpoint.state_version != 1:
            raise RuntimeError("Worker A could not publish state version 1")

        with LeaseHeartbeat(
            connection_url,
            first_checkpoint,
            interval_seconds=heartbeat_interval,
            lease_seconds=lease_seconds,
        ):
            sleep(lease_seconds + 0.5)

        after_heartbeat = get_workflow_run(connection_url, run_id)
        if after_heartbeat is None:
            raise RuntimeError("Heartbeat test run disappeared")
        if after_heartbeat.lease_generation != 1:
            raise RuntimeError("Heartbeat incorrectly changed lease generation")
        if after_heartbeat.last_heartbeat_at == after_heartbeat.lease_acquired_at:
            raise RuntimeError("Background heartbeat did not renew the lease")
        print("PASS heartbeat: generation 1 stayed live without changing generation.")

        # Stopping the heartbeat simulates a dead Python worker. Nothing remains
        # open; CockroachDB time alone makes the run eligible for reclamation.
        sleep(lease_seconds + 0.5)
        if (
            renew_workflow_lease(
                connection_url,
                run_id=run_id,
                worker_id=worker_a,
                lease_generation=1,
                lease_seconds=lease_seconds,
            )
            is not None
        ):
            raise RuntimeError("Expired generation 1 unexpectedly renewed")

        worker_b = f"worker-b-{uuid4()}"
        second_lease = claim_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=worker_b,
            lease_seconds=lease_seconds,
        )
        if second_lease is None or second_lease.lease_generation != 2:
            raise RuntimeError("Worker B did not reclaim generation 2")

        stale_publish = publish_checkpoint(
            connection_url,
            run_id=run_id,
            worker_id=worker_a,
            lease_generation=1,
            expected_state_version=1,
            checkpoint_id="stale-checkpoint-must-not-publish",
            current_round="stale",
            next_nodes=("must_not_run",),
        )
        if stale_publish is not None:
            raise RuntimeError("Stale generation 1 published after generation 2 claimed")

        second_checkpoint = publish_checkpoint(
            connection_url,
            run_id=run_id,
            worker_id=worker_b,
            lease_generation=2,
            expected_state_version=1,
            checkpoint_id="checkpoint-generation-2",
            current_round="decision",
            next_nodes=("decide_return",),
        )
        if second_checkpoint is None or second_checkpoint.state_version != 2:
            raise RuntimeError("Current generation 2 could not publish state version 2")

        completed = release_workflow_run(
            connection_url,
            run_id=run_id,
            worker_id=worker_b,
            lease_generation=2,
            new_status="completed",
        )
        if completed is None or completed.run_status != "completed":
            raise RuntimeError("Worker B could not complete and release the run")
        if any(
            value is not None
            for value in (
                completed.lease_owner,
                completed.lease_acquired_at,
                completed.last_heartbeat_at,
                completed.lease_expires_at,
            )
        ):
            raise RuntimeError("Completed run retained active lease fields")

        print(
            "PASS fencing: expired generation 1 was rejected; generation 2 "
            "published and completed the run."
        )
        print("Workflow lease smoke test completed successfully.")
        return 0
    finally:
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute("DELETE FROM workflow_runs WHERE run_id = %s", (run_id,))
            connection.execute(
                "DELETE FROM return_requests WHERE return_request_id = %s",
                (return_request_id,),
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Workflow lease smoke test failed: {error}", file=sys.stderr)
        raise

