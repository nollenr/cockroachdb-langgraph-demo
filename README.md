# Product Returns Graph Demo

This project demonstrates a durable product-return workflow built with Python,
LangGraph/LangChain, and CockroachDB. The workflow classifies an incoming
request, gathers order/policy/fraud evidence in parallel, pauses durably for
manager approval when required, and issues an idempotent refund.

## Where commands run

The Windows repository is source only. **Do not run the application, Python
environment, migrations, or tests on Windows.** WinSCP **Keep Remote Directory
up to date** copies local repository changes in one direction to:

```text
/home/ec2-user/langchain/product-returns
```

Run every command below from the AWS Linux host. Use PuTTY for an interactive
shell and PuTTY/Plink for automated SSH; do not use PowerShell/OpenSSH for SSH.

See `PROJECT-STATUS.md` for durable project context, current decisions, and the
next task.

## TL;DR: restart the existing demo

Use this path after reopening VS Code or restarting the existing EC2 host. Do
not recreate the database, rerun migrations, reingest policy vectors, or call
`CockroachDBSaver.setup()` unless the environment is actually being rebuilt.

Connection and deployment facts:

- AWS host: `ec2-user@3.23.64.12` (`i-05c2574bc30900e89`)
- Remote repository: `/home/ec2-user/langchain/product-returns`
- Python environment: `/home/ec2-user/.venvs/product-returns`
- PuTTY key: `C:\Users\RonNollen\Documents\Key-Pairs\nollen-cockroach-revenue-us-east-2-kp01.ppk`
- Required SSH fingerprint:
  `SHA256:+S3ZyxZany8Kwni2XIHDI7phGA2Avf+OWGC4TRDghSU`
- Current graph/database level: graph version `8`, migrations through `013`
- Secrets: ignored `keys.sh` and AWS-only `api-key.sh`; never print either

From a PuTTY session on the host:

```bash
cd /home/ec2-user/langchain/product-returns
bash scripts/start_observability_stack.sh
bash scripts/start_returnflow_api.sh
bash scripts/start_presentation.sh
bash scripts/check_observability_health.sh
bash scripts/check_returnflow_runtime.sh
```

The start wrappers are safe to call when their managed service is already
running. Then open:

- ReturnFlow: `http://3.23.64.12:3002`
- Grafana: `http://3.23.64.12:3001`

If application source changed, restart the API. If presentation source changed,
run `bash scripts/build_presentation.sh` before restarting the presentation.
Use the [complete rebuild checklist](#complete-rebuild-checklist) only for a new
host, missing virtual environment, or absent database. If the EC2 public IP
changes, update the Cockroach Cloud SQL allowlist, EC2 security-group access,
and the recorded host address before troubleshooting application code.

## Customer-facing presentation

`presentation/` contains **ReturnFlow**, a Next.js customer experience derived
from the presentation patterns that worked well in the NextEra Equipment
Intelligence demo. It turns the graph architecture into a visible story:

- a customer describes a return naturally;
- order, policy, and account evidence visibly fan out in parallel;
- each node exposes its input and output;
- the retrieved policy section is quoted with its version and clause ID;
- a high-value return stops at a durable manager checkpoint and resumes after
  approval;
- a presenter-selected evidence node can fail once, stop with no worker held
  open, and resume under a new lease while successful sibling nodes remain
  complete; and
- refund idempotency, checkpoints, audit history, and observability are
  summarized as customer and operational trust signals.

The UI now invokes the live Python graph through same-origin Next.js proxy
routes. Its progress, node input/output summaries, policy citation, durable
manager pause, approval/rejection, and refund outcome all come from
CockroachDB-backed execution rather than browser timers. A clearly marked
presenter control loads all current `DEMO-*` orders from CockroachDB, without
revealing the expected outcome in the label. The API remains bound to host
loopback on port `8010`; only the presentation is public on port `3002`. See
`presentation/README.md` for the AWS-only build and startup commands.

## Complete rebuild checklist

Use this sequence when rebuilding from a clean AWS host and an absent
`product_returns` database. It intentionally does not include `DROP DATABASE`
or other destructive reset commands. Host-level installation of Python 3.11,
the CockroachDB CLI, Docker with `docker-compose`, and Node.js 24/npm is not
performed by this repository; provision those tools first and verify them with
`scripts/host-inventory.sh` and `scripts/observability_host_inventory.sh`.
On the October 22 Amazon Linux 2023 host, the installed tools are Python
3.11.16, CockroachDB CLI 26.2.7, Docker 25.0.16, Docker Compose 5.6.0, and
Node.js 24.21.0/npm 11.19.0. The committed `config.sh` explicitly points
libpq at the host's system CA bundle so Python retains `verify-full` TLS
validation on a fresh instance.

1. Start WinSCP **Keep Remote Directory up to date** and confirm this repository
   appears at `/home/ec2-user/langchain/product-returns`.
2. Confirm `keys.sh` and Linux-only `api-key.sh` exist on AWS and remain ignored
   by Git. `keys.sh` defines the database passwords and
   `GRAFANA_ADMIN_PASSWORD`; `api-key.sh` exports `OPENAI_API_KEY`. Never print
   either file. On the host, restrict both to the deployment user:

   ```bash
   chmod 600 keys.sh* api-key.sh
   ```
3. Create the host-only Python 3.11 virtual environment:

   ```bash
   cd /home/ec2-user/langchain/product-returns
   bash scripts/bootstrap-host.sh
   source /home/ec2-user/.venvs/product-returns/bin/activate
   ```

4. Load configuration and install the pinned dependencies:

   ```bash
   source ./keys.sh
   source ./api-key.sh
   source ./config.sh
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python -m pip check
   python -c "import langchain, langgraph, langchain_cockroachdb, langchain_openai, psycopg; print('Core imports successful')"
   ```

5. Create the app login and database using the passwords already in ignored
   `keys.sh`. The wrapper connects through `defaultdb`, safely quotes the app
   password, and prints no credentials:

   ```bash
   bash scripts/create_database_and_user.sh
   ```

6. Apply the schema migrations in order, then rerun `001` for final
   grants and verification:

   ```bash
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/001_runtime_privileges.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/002_business_schema.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/003_workflow_schema.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/005_observability_schema.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/006_workflow_leases.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/007_demo_payment_provider.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/008_return_quantity_reservations.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/009_return_allocation_covering_index.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/010_workflow_node_events.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/012_resilience_demo.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/013_payment_resilience_demo.sql
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/001_runtime_privileges.sql
   ```

7. Run the one-time LangGraph checkpoint setup as `ron`, then rerun
   `001_runtime_privileges.sql` again so its package-owned tables are covered
   and displayed by grant verification:

   ```bash
   python scripts/setup_langgraph_checkpoint.py
   cockroach sql --url "$CRDB_RON_URL" \
     --file migrations/001_runtime_privileges.sql
   ```

8. After reviewing the demo fixtures, validate and apply the optional seed data
   as `product_returns_app`. Migration `011` depends on both the base fixtures
   from `004` and quantity-capacity table from `008`, so apply it here rather
   than in the earlier schema-only sequence:

   ```bash
   bash scripts/explain_demo_seed.sh
   bash scripts/dry_run_demo_seed.sh
   bash scripts/apply_demo_seed.sh
   bash scripts/explain_bob_fraud_review_order.sh
   bash scripts/apply_bob_fraud_review_order.sh
   bash scripts/apply_return_quantity_reservations.sh
   ```

   Rerun `008` after seeding: its initial backfill precedes the fixture rows.
   This second pass creates capacity for all seven orders and accounts for the
   three historical refunded allocations.

9. Validate and ingest the policy embeddings (the OpenAI integration was
    installed from `requirements.txt` in step 4):

    ```bash
    bash scripts/validate_policy_ingestion.sh
    bash scripts/explain_policy_ingestion_queries.sh
    bash scripts/run_policy_ingestion.sh
    bash scripts/run_policy_retrieval_smoke_test.sh
    ```

10. Verify the request-classification graph and its durable checkpoints:

    ```bash
    bash scripts/run_classification_smoke_test.sh
    ```

11. Confirm the host has at least 4 vCPU/16 GiB, then configure and start the
    isolated Product Returns observability stack as described in
    [Observability stack](#observability-stack). The current host meets
    that requirement.

12. Run the durable graph proofs, including manager shutdown/resume and the
    provider-success/worker-failure idempotency window:

    ```bash
    bash scripts/run_workflow_lease_smoke_test.sh
    bash scripts/run_decision_smoke_test.sh
    bash scripts/run_decision_store_smoke_test.sh
    bash scripts/run_workflow_worker_smoke_test.sh
    bash scripts/run_approval_interrupt_smoke_test.sh
    bash scripts/run_refund_smoke_test.sh
    bash scripts/run_return_quantity_reservation_smoke_test.sh
    ```

13. Start the private API and public presentation, then run the live API
    proofs. The presentation proxies `/api/*` to the loopback-only API:

    ```bash
    cd /home/ec2-user/langchain/product-returns/presentation
    npm install
    cd ..
    bash scripts/build_presentation.sh
    bash scripts/start_returnflow_api.sh
    bash scripts/start_presentation.sh
    bash scripts/run_returnflow_api_smoke_test.sh
    bash scripts/run_returnflow_non_refund_api_smoke_test.sh
    bash scripts/run_returnflow_approval_api_smoke_test.sh
    bash scripts/run_returnflow_denial_api_smoke_test.sh
    bash scripts/run_returnflow_reset_smoke_test.sh
    bash scripts/run_fraud_review_api_smoke_test.sh
    bash scripts/run_activation_conflict_api_smoke_test.sh
    bash scripts/run_safety_acknowledgement_api_smoke_test.sh
    bash scripts/run_resilience_api_smoke_test.sh
    bash scripts/run_payment_resilience_api_smoke_test.sh
    ```

The embedding model is OpenAI `text-embedding-3-small` at 1,536 dimensions.
The ingestion and three-query retrieval smoke test completed successfully on
the AWS host on October 17, 2026.

## Operate the live ReturnFlow demo

After loading `keys.sh`, `api-key.sh`, and `config.sh`, manage the two services
with their PID-safe wrappers:

```bash
bash scripts/start_returnflow_api.sh
bash scripts/start_presentation.sh
bash scripts/check_returnflow_runtime.sh
```

The browser URL is `http://3.23.64.12:3002`. The Python API intentionally
listens only on `127.0.0.1:8010`; Next.js proxies the browser's `/api/*`
requests to it. Stop the services with:

```bash
bash scripts/stop_presentation.sh
bash scripts/stop_returnflow_api.sh
```

The presentation remembers its most recent synthetic run in browser storage.
Starting another story asks the API to remove that run, its checkpoints, and
its demo-provider records and to restore its item capacity. Reset is limited to
threads with the reserved `returnflow-` prefix and refuses a currently running
workflow.

## Demonstrate failure recovery and inspect one run

Before selecting **Review my return**, use the clearly marked **Resilience
test** control to fail purchase lookup, policy retrieval, or account assessment
once. The selected node records a retryable failure while its successful
parallel siblings leave pending writes in CockroachDB. The dispatcher then:

1. publishes the exact recovery checkpoint under the current lease fence;
2. changes the run to `retry_wait` with no `next_attempt_at`;
3. releases the worker lease completely; and
4. waits for the presenter to select **Resume with a new worker**.

Resume makes the run claimable. A new lease generation loads the published
checkpoint, applies the successful sibling pending writes, retries only the
failed node, and continues normally. The focused proof is:

```bash
bash scripts/run_resilience_api_smoke_test.sh
```

While the run is stopped, **Copy database inspection SQL** copies nine
read-only queries with that run's UUID already embedded. The same package is
available from `GET /returns/<run-id>/inspection-sql`, and its source template
is `sql/inspect_returnflow_run.sql`. Run the copied statements as
`product_returns_app` in the Cockroach SQL shell or DBeaver to inspect:

- `workflow_runs`, including the stopped state, published checkpoint, released
  lease, and generation;
- `workflow_failure_injections` and the selected one-shot failure;
- `node_attempts`, including successful siblings and both failed/recovered
  attempts;
- `audit_events`, including pause, resume request, and new-worker claim; and
- LangGraph `checkpoints`, `checkpoint_writes`, and `checkpoint_blobs` for the
  exact thread; and
- the provider refund ledger and local refund attempts for a payment failure.

The SQL deliberately exposes all checkpoint bookkeeping needed for this
synthetic demo. It is read-only and UUID-scoped; do not generalize that level of
state visibility to sensitive production workloads without redaction and
authorization controls.

## Demonstrate payment idempotency after provider success

Select eligible `DEMO-1001`, choose **Fail after payment-provider success**,
and submit the return. The deterministic provider commits one refund under
`product-returns:<run_id>:refund:v1`; the one-shot hook then fails
`issue_refund` before local completion. ReturnFlow shows the provider refund ID
and key while the run is stopped with a published checkpoint, no worker lease,
and no automatic retry time. Select **Resume with a new worker**. The new lease
generation repeats the provider request with the same key and receives the
original refund ID. The final proof panel shows **one refund issued, two
provider requests, zero duplicate payments**, plus local attempts, audit
events, and Grafana trace/log links.

The copied run-specific SQL has nine read-only queries, including the provider
ledger and local refund attempts. Run the public proxy proof with
`bash scripts/run_payment_resilience_api_smoke_test.sh`; it removes its
synthetic run after success. This scenario is separate from the parallel
evidence selective-replay story.

## Start a host shell

Change to the synchronized project directory:

```bash
cd /home/ec2-user/langchain/product-returns
```

Activate the existing Python 3.11 virtual environment:

```bash
source /home/ec2-user/.venvs/product-returns/bin/activate
python --version
python -m pip --version
```

Activation changes the current shell's `PATH` so `python` and `pip` resolve to
the isolated environment. It lasts only for that shell session. Use
`deactivate` to leave the environment.

Load secrets first, then load the non-secret configuration that constructs the
connection URLs from those secrets:

```bash
source ./keys.sh
source ./api-key.sh
source ./config.sh
```

`keys.sh` is intentionally synchronized to the host but ignored by Git.
`api-key.sh` exists only on Linux and is also ignored by Git. Never commit or
print either file, enable shell tracing while sourcing them, or echo the
resulting connection URLs or API key.

To verify the OpenAI variable without displaying its value, run this on AWS:

```bash
bash scripts/check_openai_environment.sh
```

The check sources `keys.sh`, `api-key.sh`, and `config.sh`, then confirms that
`OPENAI_API_KEY` is non-empty and exported to a child process. It passed in a
fresh Plink session on October 17, 2026.

## Python dependencies

The core project dependencies were installed successfully in the AWS-host
Python 3.11 virtual environment. `requirements.txt` pins:

```text
langchain==1.4.1
langgraph==1.2.12
langchain-cockroachdb==0.4.0
langchain-openai==1.7.2
opentelemetry-api==1.45.1
opentelemetry-sdk==1.45.1
opentelemetry-exporter-otlp-proto-http==1.45.1
prometheus-client==0.26.0
psycopg[binary]==3.3.6
psycopg-pool==3.3.3
```

Install it inside the activated environment with:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

These are direct dependency pins; pip will resolve their transitive
dependencies during installation. OpenAI `text-embedding-3-small` is the
selected embedding model. `langchain-openai` 1.7.2 was resolver-checked,
installed, and import-tested on AWS on October 17, 2026. The graph's
conversational LLM remains a separate decision.

The AWS-host resolver dry run completed with no dependency conflicts. The real
installation then completed, and imports of `langchain`, `langgraph`,
`langchain_cockroachdb`, `langchain_openai`, and `psycopg` succeeded. `pip
check` reported no broken requirements.

For an existing environment that predates the `langchain-openai` pin, the
incremental installer is `bash scripts/install_openai_integration.sh`.

## Database schema and migrations

Run owner/deployment operations with `CRDB_RON_URL`. The application itself
uses the least-privilege `CRDB_APP_URL`.

The repository currently contains eleven schema/security migrations and two
optional demo-data migrations:

1. `migrations/001_runtime_privileges.sql`
   - Removes broad public access.
   - Grants the application database/schema access.
   - Gives `product_returns_app` CRUD access to current and future tables
     created by `ron`.
2. `migrations/002_business_schema.sql`
   - Creates customers, products, orders, order items, return policies,
     attributable policy clauses, the `VECTOR(1536)` policy-chunk store, and
     return requests/items.
3. `migrations/003_workflow_schema.sql`
   - Creates workflow runs, independent node attempts, durable approval
     requests, logical refunds, refund attempts, and audit events.
4. `migrations/004_demo_seed.sql`
   - Adds deterministic, rerunnable demo fixtures after the schema is ready.
   - Is applied with the runtime application identity only after validation and
     review.
5. `migrations/005_observability_schema.sql`
   - Adds trace/span correlation columns, sanitized node input/output state,
     and covering indexes used by the Grafana run-inspection queries.
6. `migrations/006_workflow_leases.sql`
   - Adds renewable run ownership, per-run generation fencing, graph-version
     compatibility, lease invariants, and the expired-run scheduler index.
7. `migrations/007_demo_payment_provider.sql`
   - Creates the isolated provider-side ledger used to prove that a repeated
     idempotency key returns one refund rather than creating a duplicate.
8. `migrations/008_return_quantity_reservations.sql`
   - Adds per-order-item purchased/reserved/refunded capacity and the request
     allocation ledger, including backfill of historical returns.
9. `migrations/009_return_allocation_covering_index.sql`
   - Adds the covering unique key used for idempotent allocation lookup and
     request-level release/finalization.
10. `migrations/010_workflow_node_events.sql`
   - Extends `node_attempts` with the sanitized input snapshot and node duration
     used by the live ReturnFlow journey and durable per-node audit display.
11. `migrations/011_bob_fraud_review_order.sql`
   - Adds a recent, otherwise eligible Bob order so the restricted-account and
     prior-refund signals alone demonstrate fraud/risk-driven manager review.
   - Runs after both `004_demo_seed.sql` and
     `008_return_quantity_reservations.sql`; stable UUIDs and conflict-safe DML
     make it rerunnable.
12. `migrations/012_resilience_demo.sql`
   - Adds one durable, one-shot presenter failure plan per run. A plan records
     the chosen parallel evidence node and its planned, triggered, and resumed
     timestamps; it never stores credentials or replaces LangGraph state.
13. `migrations/013_payment_resilience_demo.sql`
   - Adds the payment-provider-success mode to the existing one-shot plan.
     The provider ledger and unique idempotency key are unchanged.

Python declares graph version `8` in `product_returns/graph_version.py`.
Committed `config.sh` asserts that the deployment expects version `8`; it does
not define the authoritative version. It also sets a 30-second lease and a
10-second heartbeat interval. Lease calculations use CockroachDB `now()`; the
worker's local clock is not authoritative.

`workflow_runs.graph_version` intentionally has no database default. Existing
pre-version rows are backfilled to version `1` by migration `006`, but Python
must explicitly provide the source-controlled graph version for every new run.

## Graph version and workflow ownership

`product_returns/graph_version.py` contains the source-controlled
`CURRENT_GRAPH_VERSION` and a semantic manifest of nodes, routes, state schema,
and node contracts. Both graph builders validate its registered SHA-256
signature. A structural manifest change without an intentional version and
signature update fails before the graph is built. `EXPECTED_GRAPH_VERSION` in
`config.sh` is a deployment assertion; a mismatch with the Python constant also
fails startup.

`product_returns/workflow_runs.py` provides the durable run lifecycle:

1. `create_workflow_run()` explicitly stores the current graph version.
2. `claim_workflow_run()` atomically claims ready/due work or reclaims an
   expired run, incrementing the per-run fencing generation.
3. `LeaseHeartbeat` renews ownership in a daemon thread using CockroachDB time.
4. `publish_checkpoint()` advances `latest_checkpoint_id` and `state_version`
   only when owner, generation, live lease, graph version, and expected state
   version all still match.
5. `commit_return_decision()` atomically changes workflow and return-request
   status, optionally creates a pending manager approval, appends the complete
   decision audit event, and clears the lease using the same ownership fence.
6. `release_workflow_run()` handles other terminal or retry transitions that
   do not need the decision-specific multi-row commit.
7. `commit_refund_completion()` verifies the checkpointed provider result and
   atomically completes the run, marks the request refunded, appends the full
   decision/refund audit event, and clears the fenced lease.

Normal terminal and approval recovery uses `langgraph_checkpoint_config(run)`
to pin execution to the application-published checkpoint. Parallel-node error
recovery uses `PinnedResumeCockroachDBSaver`: the saver reads that same exact
published checkpoint, but the public LangGraph invocation omits
`checkpoint_id`. This distinction matters because LangGraph treats an explicit
ID as a historical fork and intentionally does not apply pending writes in
that mode. The adapter therefore preserves both fencing and selective replay.
A stale worker may write an orphan checkpoint after losing its lease, but it
cannot publish it in `workflow_runs` and the adapter will not load it.

The basic worker shape is:

```python
lease = claim_workflow_run(
    connection_url,
    run_id=run_id,
    worker_id=worker_id,
    lease_seconds=30,
)
if lease is None:
    return

with LeaseHeartbeat(
    connection_url,
    lease,
    interval_seconds=10,
    lease_seconds=30,
) as heartbeat:
    result = graph.invoke(None, langgraph_checkpoint_config(lease))
    heartbeat.raise_if_lost()
    # Read the resulting checkpoint ID, then publish it with
    # publish_checkpoint(..., expected_state_version=lease.state_version).

# Release only after the checkpoint has been published successfully.
```

Run the repeatable database-backed proof on AWS with:

```bash
bash scripts/run_workflow_lease_smoke_test.sh
```

`product_returns/workflow_worker.py` joins this ownership layer to a compiled
LangGraph. It executes with synchronous checkpoint durability and consumes
`stream_mode="checkpoints"`, then publishes the last checkpoint event emitted
by that exact invocation. It does not query the thread's unqualified latest
checkpoint, so a stale worker's orphan checkpoint cannot be mistaken for the
current worker's result.

The end-to-end recovery proof uses the real classifier, three evidence
branches, deterministic decision, quantity reservation, and final refund node:

```bash
bash scripts/run_workflow_worker_smoke_test.sh
```

The test deliberately leaves Worker A's run in `running` after its checkpoint
is durably published, waits for the lease to expire, and lets Worker B reclaim
generation 2. Worker B loads the explicitly published checkpoint, observes
that it is terminal for the current graph, skips every completed node, and
atomically finalizes the already checkpointed provider refund with its
policy-backed decision in `audit_events`. Temporary workflow, refund, provider,
request, audit, and checkpoint data are removed afterward.

## Deterministic return decision and durable reason

Graph version `2` adds `decide_return` after the three parallel evidence
branches. The node is deterministic: it does not ask a model to interpret the
business rules. It evaluates the 30-day window, final-sale gift cards,
activated-phone exclusion or activation-evidence conflict, order/customer
facts, fraud-review signals, and the strictly-greater-than-$500 manager
threshold. Its output includes stable reason codes, a factual explanation,
refund amount, relevant verified policy clauses, and the facts used in the
decision.

`product_returns/decision_store.py` persists that result in one short,
retryable CockroachDB transaction. Therefore finishing without a refund is an
explicit business outcome, not a generic exception: the request is marked
`rejected`, the workflow is terminal, and a `return_rejected` audit event keeps
the exact reason, facts, citations, graph version, lease generation, state
version, and LangGraph checkpoint ID. Manager-review cases instead become
`waiting_for_approval` with a durable pending `approval_requests` row. Eligible
requests at or below $500 route through `reserve_return_items` and then to
`issue_refund` only when the requested quantities remain available.

Run the rule and database-persistence proofs on AWS with:

```bash
bash scripts/run_decision_smoke_test.sh
bash scripts/run_decision_store_smoke_test.sh
```

## Durable manager approval interrupt and resume

Graph version `3` routes `requires_approval` decisions to
`await_manager_approval`. That node calls LangGraph `interrupt()`, so its
checkpoint has the approval node as pending work. `commit_return_decision()`
then creates the pending `approval_requests` row, changes the workflow to
`waiting_for_approval`, and clears every lease field. No Python process,
thread, connection, or in-memory graph remains necessary while the manager
decides.

Record a response from the AWS repository after loading the normal environment:

```bash
python scripts/manager_decision.py RUN_UUID \
  --approve \
  --manager 'manager.name' \
  --note 'Approved after reviewing the order and policy.'
```

Use `--reject` instead of `--approve` for a rejection. The command atomically
updates the pending approval, appends the manager audit event, increments the
application state version, and changes the workflow to `ready`. A later worker
claims a new lease generation, loads that response from CockroachDB, and sends
it to the exact published checkpoint as `Command(resume=...)`. The interrupt
node restarts, receives the response, and checkpoints `manager_decision` into
graph state. Approval continues directly through `issue_refund`; rejection
finishes with `return_rejected_by_manager` and the manager's identity and note.

Run both complete paths with:

```bash
bash scripts/run_approval_interrupt_smoke_test.sh
```

The test closes the first checkpointer before the human action, proves a
waiting run has no lease and cannot be claimed, then creates a new generation-2
worker to resume. The approved path issued and finalized its refund; the
rejected path issued none. Both paths passed against CockroachDB.

## Idempotent refund execution

Graph version `4` adds `issue_refund`. `product_returns/refund.py` derives the
stable provider key `product-returns:<run_id>:refund:v1`, creates an auditable
local attempt, calls the provider outside the local database transaction, and
then records provider success. The demo provider ledger has a unique
`idempotency_key`; a retry increments `request_count` but returns the original
`provider_refund_id`.

This covers the dangerous failure window: the provider may succeed and the
Python worker may die before local completion. The next attempt marks the
abandoned local attempt `retryable_failure`, calls the provider with the same
key, and safely completes with the same refund ID.

```bash
bash scripts/run_refund_smoke_test.sh
```

The test injects a failure immediately after the first provider success. It
proves two provider requests produced one provider refund, preserves both local
attempts, checkpoints `refund_result`, and atomically completes the workflow,
return request, and audit event.

## Concurrent return-quantity protection

Graph version `5` adds `reserve_return_items` between the decision and either
approval or refund. Protection is per purchased order item and quantity, so one
order can still have separate legitimate partial returns.

The current UI-free demo requests every item and its full purchased quantity
from the order lookup. A later API can supply a selected subset and quantities;
the reservation model and invariant already support partial returns.

`return_item_capacity` tracks purchased, currently reserved, and already
refunded units. `return_item_allocations` records which return request owns each
reservation. A short serializable transaction uses a guarded atomic update:

```text
reserved quantity + refunded quantity + newly requested quantity
<= purchased quantity
```

The lifecycle is explicit:

- An eligible in-progress request holds `reserved` quantity.
- Manager rejection changes its allocation to `released`, making it reusable.
- Refund completion changes it to `refunded`, making it permanently consumed.
- A competing or later request becomes an audited
  `RETURN_QUANTITY_UNAVAILABLE` business rejection; it never calls the payment
  provider.

Run the simultaneous-request proof with:

```bash
bash scripts/run_return_quantity_reservation_smoke_test.sh
```

## AI-grounded customer claims

Graph version `6` extends the classifier's strict structured output with a
device-activation claim. The model may identify `activated`, `not_activated`,
or `unspecified`, but an explicit claim is accepted only when its supporting
text is a verbatim substring of the customer's original message. Invalid or
ungrounded extraction is safely reduced to `unspecified`.

The model does not decide policy or override CockroachDB. Deterministic Python
compares the verified customer claim with the authoritative
`order_items.activated_at` value. For `DEMO-1004`, “has not been activated”
conflicts with the recorded activation timestamp, producing
`ACTIVATION_STATUS_CONFLICT` and the customer-facing explanation:

> We found conflicting activation information. Our records indicate that this
> phone was activated, while your request says it was not. This return requires
> manual review.

The workflow then uses the existing durable manager interrupt. Both facts, the
source quote, reason code, policy citations, and human decision remain in the
checkpoint and audit trail. Prove the complete public path with:

```bash
bash scripts/run_activation_conflict_api_smoke_test.sh
```

Graph version `7` also extracts explicit potential product-safety concerns into
a separate grounded structure. Categories include overheating, smoke/fire,
electric shock, injury, and property damage. The model-provided supporting text
must occur verbatim in the original request or the extraction is discarded.

This insight is deliberately non-routing: it does not make a return eligible,
ineligible, or subject to approval. Existing deterministic order, policy, risk,
and refund rules remain authoritative. When an otherwise eligible customer
reports that a toaster gets dangerously hot, the completed decision preserves
the quote, records `POTENTIAL_PRODUCT_SAFETY_CONCERN`, and tells the customer
that the concern was recorded for product-safety follow-up. It does not claim
that a manufacturer or external system was contacted. Prove the live path with:

```bash
bash scripts/run_safety_acknowledgement_api_smoke_test.sh
```

The API snapshot reader retries the entire serializable read transaction with
bounded exponential backoff. This prevents transient CockroachDB uncertainty
or serialization retries from surfacing as browser errors while graph nodes
are concurrently publishing progress.

The first three migrations were applied successfully on October 16, 2026;
migrations `005` and `006` were applied on October 19, migrations `007`
through `011` on October 20, and migrations `012` and `013` on October 21, 2026.
Migration `011` is demo data and is applied after `004` and `008`, as shown in
the seed section. The commands below
are retained as the schema rebuild procedure and should be run in order:

```bash
cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/001_runtime_privileges.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/002_business_schema.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/003_workflow_schema.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/005_observability_schema.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/006_workflow_leases.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/007_demo_payment_provider.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/008_return_quantity_reservations.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/009_return_allocation_covering_index.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/010_workflow_node_events.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/012_resilience_demo.sql

cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/013_payment_resilience_demo.sql
```

Then rerun `001` to apply and verify table grants. It is designed to be
rerunnable:

```bash
cockroach sql --url "$CRDB_RON_URL" \
  --file migrations/001_runtime_privileges.sql
```

Do not run schema migrations with `CRDB_APP_URL`.

## LangGraph checkpoint schema setup

LangGraph's CockroachDB checkpointer owns an additional set of internal tables
that stores serialized graph state, pending work, and checkpoint history. We do
not reproduce those package internals in our SQL migrations.

After `langchain-cockroachdb` is installed, run the repository's reviewed setup
command using the owner URL:

```bash
python scripts/setup_langgraph_checkpoint.py
```

The script validates that `CRDB_RON_URL` uses owner `ron` and targets database
`product_returns`, without printing the URL or its password. Internally, it
performs the equivalent of:

```python
import os

from langchain_cockroachdb import CockroachDBSaver

with CockroachDBSaver.from_conn_string(os.environ["CRDB_RON_URL"]) as saver:
    saver.setup()
```

This is a deployment-time schema step, not normal application startup. Normal
graph execution will construct the saver with `CRDB_APP_URL` and will not call
`setup()`.

After checkpoint setup, rerun `001_runtime_privileges.sql` and verify the
package-created tables also grant CRUD access to `product_returns_app`.

The setup completed successfully on October 16, 2026, and created these
package-owned tables:

- `checkpoints`
- `checkpoint_blobs`
- `checkpoint_writes`
- `checkpoint_migrations`

After rerunning migration `001`, `product_returns_app` has `SELECT`, `INSERT`,
`UPDATE`, and `DELETE` on all four LangGraph tables. With all current workflow,
provider, capacity, observability, and resilience objects, the database has 19
application-owned tables and four LangGraph-owned tables: 23 total tables and
92 verified table-grant rows.

Verify actual runtime access with a deterministic, no-LLM smoke test:

```bash
bash scripts/run_checkpoint_smoke_test.sh
```

The wrapper activates the host virtual environment and loads `keys.sh`, then
`api-key.sh`, then `config.sh`. The Python test refuses owner credentials, does
not call `setup()`, and uses
`CRDB_APP_URL` to run a one-node graph. It writes, reads, and lists the resulting
checkpoints, verifies the persisted state, and deletes its temporary thread on
success. A failed test leaves its thread data available for diagnosis.

This smoke test completed successfully on October 16, 2026, using
`product_returns_app`. It verified three checkpoints and cleaned up the
temporary thread.

CockroachDB vector search is selected for policy retrieval. The embedding model
is OpenAI `text-embedding-3-small` using its default 1,536 dimensions, so the
`policy_chunks` table uses `VECTOR(1536)`. It was created on October 17, 2026,
with the connector-compatible columns `id`, `namespace`, `content`,
`embedding`, `metadata`, and `created_at`, plus a namespace index. It contains
eight verified chunks in namespace `standard-returns:1.0`, one for each policy
section. Exact cosine search is appropriate for this small corpus, so no
approximate vector index is present.

## Return-policy source and retrieval

The customer-facing source document is
`policies/standard-return-policy-v1.md`. Its section headings contain stable
clause identifiers so an ingestion job can preserve provenance while chunking
the document.

The implemented policy pipeline is:

1. Hash and register the source document/version in `return_policies`.
2. Parse its identified sections into authoritative `policy_clauses` rows.
3. Chunk and embed the text into a CockroachDB vector-store table.
4. Retrieve candidate chunks semantically in the policy graph node.
5. Verify every result against the active policy version, clause identifier,
   source hash, and authoritative clause text before using it in a decision.

The vector table is a derived search index; the Markdown document and
relational policy records remain the source of truth.

Each vector-store record must preserve citation metadata alongside the chunk:

- `document_title`
- `policy_key`
- `policy_version`
- `section_heading`
- `clause_key`
- `source_uri`
- `content_sha256`
- `chunk_index`
- `embedding_model`
- `embedding_dimensions`
- `return_policy_id`
- `policy_clause_id`

Page numbers are intentionally not required because the authoritative source
is Markdown. A policy result is quoted using the document title, version,
section heading, and clause identifier. The clause identifier and source hash
must be verified against the relational policy records before the quote is used
in a return decision.

The OpenAI API key is exported as `OPENAI_API_KEY` by Linux-only, ignored
`api-key.sh`. Keep the non-secret model name and dimension in `config.sh`.

The ingestion is deterministic and rerunnable: it parses the identified
Markdown sections, verifies them against the authoritative relational clauses,
uses stable UUIDs within the configured namespace, upserts their embeddings,
removes stale namespace rows only after successful writes, and validates every
stored row. Run it with:

```bash
bash scripts/validate_policy_ingestion.sh
bash scripts/explain_policy_ingestion_queries.sh
bash scripts/run_policy_ingestion.sh
bash scripts/run_policy_retrieval_smoke_test.sh
```

The October 17 smoke test retrieved and verified the expected clause in the
top three results for a gift card, a $700 refund, and an ordinary product 45
days after purchase. Each displayed quote was checked against the relational
policy record before it was reported.

## Request-classification graph

The first application graph slice is implemented in the `product_returns`
Python package. `state.py` defines the durable typed state; its order, policy,
and fraud result fields are deliberately independent so later parallel nodes
can update their own result without replacing successful sibling results.

`classification.py` uses structured output to assign exactly one intent:

- `refund` — an explicit return, exchange, or refund request
- `complaint` — dissatisfaction without a return/refund request
- `other` — a clearly different customer-service request
- `ambiguous` — insufficiently clear intent that needs clarification

Classification does not decide eligibility, policy, fraud, approval, or refund
amount. The configured classifier is OpenAI `gpt-6-luna` with reasoning effort
`none`; both values are non-secret settings in `config.sh`. The result written
to graph state records the intent, confidence, short rationale, clarification
flag, model, reasoning effort, a grounded device-activation claim, and a
separately grounded potential product-safety concern. Each extraction contains
verbatim supporting text and a deterministic verification flag so downstream
code never trusts an unsupported model assertion.

Run the AWS-only checkpoint-backed test with:

```bash
bash scripts/run_classification_smoke_test.sh
```

The current six-path test correctly classifies explicit refund, explicit
complaint, and ambiguous messages, extracts “has not been activated,” verifies
the quote in the original message, extracts and grounds a toaster safety
concern, checks every CockroachDB LangGraph checkpoint, and removes all
temporary test threads.

## Parallel evidence round

Refund requests now fan out from `classify_request` to three independent nodes:

- `lookup_order` verifies that the supplied customer owns the order and returns
  immutable order/item facts plus the item-level refundable total. An unknown
  order is a valid `found=false` result, not an infrastructure exception.
- `retrieve_policy` embeds the request, searches the CockroachDB vector store,
  and verifies every returned clause against the active relational policy,
  document hash, IDs, source URI, embedding model, and dimensions before it can
  be written to state.
- `assess_fraud` applies transparent demo rules to account status and prior
  completed-refund history. It returns signals and a review recommendation; it
  does not declare that the customer committed fraud.

Each node writes only its own typed state field. A node-level LangGraph retry
policy retries transient database/infrastructure failures and failed policy
verification without restarting successful sibling branches. Non-refund
intents leave the graph immediately after classification.

Validate the three new SQL access paths and run the AWS-only, checkpoint-backed
test with:

```bash
bash scripts/explain_evidence_queries.sh
bash scripts/run_evidence_round_smoke_test.sh
```

On October 19, 2026, all three `EXPLAIN` operations succeeded using the expected
customer, order, order-item, policy, and return-history indexes. The smoke test
deliberately failed `assess_fraud` on its first attempt. LangGraph retried only
that branch: order lookup ran once, policy retrieval ran once, and fraud ran
twice. The completed checkpoint contained all three results and four checkpoint
history entries, then the temporary thread was removed. Prometheus also captured
the three successes and deliberate failure; the corresponding inputs, outputs,
error, and retry are available in Grafana/Loki/Tempo.

## Demo seed data

`migrations/004_demo_seed.sql` is a rerunnable fixture migration using stable
UUIDs and CockroachDB `UPSERT`. It seeds:

- Ron, Sally, and Bob; Bob has a restricted account.
- A toaster, coffee maker, vacuum, gift card, and mobile phone.
- Six orders covering an eligible low-value return, manager approval over $500,
  a gift-card exclusion, an activated-phone exclusion, an expired return
  window, and historical return activity.
- Return-policy version 1.0 and its eight attributable clauses, linked to the
  Markdown source and SHA-256 hash.
- Three completed historical returns for Bob, giving the fraud node genuine
  business facts to evaluate.

`demo/return_requests.json` contains the new customer messages used to exercise
the graph. They are intentionally not inserted as active `return_requests`;
graph execution will create those records.

Validate every seed DML/query plan without applying data:

```bash
bash scripts/explain_demo_seed.sh
bash scripts/dry_run_demo_seed.sh
```

The second command executes all DML to enforce values, uniqueness, checks, and
foreign keys, but replaces `COMMIT` with `ROLLBACK`; it leaves no seed rows.
Both validations completed successfully on the AWS host on October 16, 2026.
The rollback test accepted 3 customers, 5 products, 6 orders, 6 order items,
1 policy, 8 clauses, 3 historical return requests, and 3 historical return
items, then confirmed that zero seed rows persisted.

After review and successful validation, apply the seed migration as the runtime
application identity:

```bash
cockroach sql --url "$CRDB_APP_URL" \
  --file migrations/004_demo_seed.sql
```

The migration was applied successfully on October 17, 2026. The database now
contains the listed 3 customers, 5 products, 6 base orders, 6 base order items,
1 policy, 8 clauses, 3 historical return requests, and 3 historical return
items. The preferred rerunnable wrapper is `bash scripts/apply_demo_seed.sh`.

After migration `008` has created and backfilled item capacity, add the seventh
presenter order and its capacity row:

```bash
bash scripts/explain_bob_fraud_review_order.sh
bash scripts/apply_bob_fraud_review_order.sh
```

`DEMO-1007` is Bob's recent, returnable `$140.39` coffee-maker purchase. It is
below the dollar threshold and within the return window, so its only approval
reason is `FRAUD_REVIEW_REQUIRED`: Bob's restricted account contributes 60 risk
points and his three prior refunded returns contribute 30. The live fraud-only
proof is `bash scripts/run_fraud_review_api_smoke_test.sh`. With `011` applied,
the current fixture inventory is 3 customers, 5 products, 7 orders, and 7 order
items.

## Observability stack

The demo uses an isolated, pinned Docker Compose stack under `observability/`:

- Grafana 13.2.2 on host port `3001` is the only externally reachable UI.
- Prometheus 3.13.3 is bound to host loopback port `9091` and stores
  low-cardinality node counts, failures, concurrency, and latency.
- Tempo 3.1.0 is bound to loopback port `3200` and stores OpenTelemetry traces.
- Loki 3.7.8 is bound to loopback port `3100` and stores structured node-event
  logs, including sanitized node input and output state.
- Alloy 1.20.1 receives OTLP/HTTP on loopback port `4318`, forwards traces to
  Tempo, and tails the application JSONL log into Loki.

This stack has its own Compose project, Docker network, and named volumes. The
new `t3a.xlarge` host has 4 vCPU, 15 GiB usable RAM, and about 247 GiB free
disk before pulling the images, meeting the working recommendation for this
demo.

The stack was started on October 22, 2026. All five readiness endpoints passed
and all containers reported zero restarts. `PRODUCT_RETURNS_OTLP_ENABLED` is
`true`.

Add a new secret to AWS-only, Git-ignored `keys.sh`:

```bash
export GRAFANA_ADMIN_PASSWORD='<a-new-demo-admin-password>'
```

Validate without pulling images or starting containers:

```bash
bash scripts/validate_observability_stack.sh
```

After adding the Grafana password, start and inspect the stack:

```bash
bash scripts/check_observability_prerequisites.sh
bash scripts/start_observability_stack.sh
bash scripts/status_observability_stack.sh
```

Open `http://3.23.64.12:3001`. The Windows desktop confirmed HTTP 200 on this
port. Sign in as `admin` with the password from
`keys.sh`; do not expose port 3001 broadly to the Internet.

In Grafana, select **Dashboards -> Browse -> Product Returns -> Product Returns
— Graph Operations**, or open the dashboard directly:

```text
http://3.23.64.12:3001/d/product-returns-graph-operations/product-returns-graph-operations
```

The provisioning API verified this dashboard UID successfully on October 22,
2026. The folder itself also appears in dashboard searches, so a search for
"Product Returns" can return both the folder and the dashboard.

After an EC2 public-IP change, add the new address as a `/32` SQL entry in the
Cockroach Cloud cluster IP allowlist before running graph tests. Add and test
the new entry before removing the former entry. The current required entry is
`3.23.64.12/32`; it was added and successfully tested on October 22, 2026.

Once Alloy and Tempo are running, enable trace export in `config.sh`:

```bash
export PRODUCT_RETURNS_OTLP_ENABLED='true'
```

Application JSON events are written outside the synchronized repository at
`/home/ec2-user/.local/state/product-returns/logs/events.jsonl`. Each node span
has `node.input` and `node.output` events, and each JSON log includes the full
sanitized input or output delta plus `run_id`, `thread_id`, `trace_id`, and
`span_id`. Grafana's provisioned **Product Returns — Graph Operations**
dashboard shows node metrics and logs. Click a log's derived `TraceID` link to
open its Tempo trace and node graph. Every node in one durable workflow run,
including nodes executed on separate parallel worker threads, receives the
same trace ID derived from that random run UUID. Individual node spans retain
their own span IDs. Credentials remain redacted.

The dashboard also includes retained counters for presenter-injected failures,
published recovery checkpoints, and manual resumptions. Loki retains the
failed-node event and later successful attempt, while Tempo retains the spans
produced by each worker invocation. CockroachDB remains the authoritative view
of the stopped run, released lease, exact checkpoint, and complete audit
sequence.

Prometheus intentionally does not use run/customer/request identifiers as
metric labels; those high-cardinality identifiers belong in traces, logs, and
CockroachDB. Instrumented smoke processes expose port 8000 while they run and
wait—up to a bounded timeout—until Prometheus confirms the expected metrics
were stored. The dashboard uses retained `max_over_time` samples so those
metrics remain visible after the short-lived process exits. This scrape window
is test instrumentation and does not alter the workflow rule that nothing
stays open while waiting for manager approval.

Generate and verify the current five-node end-to-end view with:

```bash
bash scripts/run_workflow_worker_smoke_test.sh
bash scripts/check_workflow_observability.sh
```

The verifier selects the latest successful `decide_return` event from Loki,
opens its trace ID in Tempo, confirms that the same trace contains
classification, all three evidence nodes, and the decision node, checks all
five Prometheus metrics, and confirms the Grafana dashboard is provisioned.

Final end-to-end verification on October 19, 2026 found 9 classifier traces in
Tempo, 18 structured events in Loki, a Prometheus classifier success counter of
3, and the provisioned dashboard with its batch-compatible metric queries.
On October 20, the complete workflow verifier found one correlated trace with
all five current graph-node spans, all five node metrics, and the final decision
event in Loki.

Stop the containers while preserving all named data volumes with:

```bash
bash scripts/stop_observability_stack.sh
```

## Fraud assessment state

Fraud assessment is a graph-node result, not a business table. The node writes
a structured assessment—result, risk score, evidence codes, and timestamp—to
LangGraph state. The CockroachDB checkpoint preserves that state, while
`node_attempts` and `audit_events` retain appropriate summaries and provenance.

For the initial demo, the node can derive evidence from existing business data
such as account status, order ownership, prior return activity, and requested
refund amount. A later external fraud service can replace or supplement that
logic without changing the business schema.

Products and order items also retain a product category, and order items have
an optional activation timestamp. Those authoritative facts let deterministic
rules enforce gift-card and activated-phone exclusions without inferring facts
from product names. AI-extracted customer claims remain separately labeled and
must be grounded in the original message before comparison with those records.

## Current safe execution order

1. For an existing host, use the five start/health commands in
   [TL;DR: restart the existing demo](#tldr-restart-the-existing-demo). The
   wrappers source the required environment files themselves.
2. Never rerun setup, schema creation, seed ingestion, or policy ingestion just
   because VS Code, PuTTY, or the EC2 processes restarted.
3. After Python changes, restart the API. After presentation changes, run
   `scripts/build_presentation.sh`, then restart the presentation.
4. Run `scripts/run_resilience_api_smoke_test.sh` to validate the live
   evidence-node failure/resume path through the same proxy used by the browser.
5. Run `scripts/run_payment_resilience_api_smoke_test.sh` to verify the live
   provider-success, manual resume, and idempotency proof.
6. Use the complete rebuild checklist only when the host, virtual environment,
   or database is genuinely absent.

Do not run an unreviewed migration or expose connection URLs, passwords, API
keys, or provider responses in terminal output or source control.
