# Product Returns Graph — Project Context and Status

## New deployment completed — 2026-10-22

- Current EC2 instance: `i-05c2574bc30900e89` at `3.23.64.12`, Amazon Linux 2023 `t3a.xlarge` (4 vCPU, 15 GiB RAM). The user confirmed the WinSCP one-way mirror points there. PuTTY on that instance independently reported the ED25519 fingerprint `SHA256:+S3ZyxZany8Kwni2XIHDI7phGA2Avf+OWGC4TRDghSU`, matching Plink; all automation pins it.
- Installed Python 3.11.16, Git, Docker 25.0.16, Docker Compose 5.6.0, Node.js 24.21.0/npm 11.19.0, CockroachDB CLI 26.2.7, the project virtual environment, and pinned Python/npm dependencies. `pip check`, TypeScript checking, the Next.js production build, and npm audit all passed.
- The new CockroachDB cluster is reachable from the new EC2 IP after adding `3.23.64.12/32` to its SQL allowlist. `config.sh` now specifies the system CA bundle for `verify-full` libpq TLS on a fresh host. Created database `product_returns` and app user `product_returns_app`; the owner is `ron`, and the database primary region is `aws-us-east-2`.
- Applied migrations through `013`, set up LangGraph checkpoints, loaded all seven synthetic orders, and embedded eight verified policy sections. Reran migration `008` after seeding to backfill seven capacity rows and three historical refunded allocations. Read-only verification found 23 tables, 92 app CRUD grants, seven orders, eight policy chunks, zero active synthetic runs, nine purchased units, zero reserved units, and three historically refunded units.
- Grafana, Prometheus, Tempo, Loki, and Alloy are running with five healthy endpoints and zero container restarts. The private API and public Next.js presentation are running. Windows HTTP checks returned 200 for `http://3.23.64.12:3002/` and `http://3.23.64.12:3001/api/health`.
- The mirrored `keys.sh*` files and host-only `api-key.sh` initially arrived with permissive modes; all were changed to owner-only `0600` on the new host. Recheck permissions after WinSCP replaces any secret file.
- Live tests passed for automatic refund, approval pause/resume, gift-card denial, non-refund, fraud review, activation conflict, safety acknowledgement, evidence-node recovery, payment-provider idempotency, and synthetic reset. Observability checks found correlated traces, five node spans/metrics, Loki events, and the provisioned Grafana dashboard.
- The previous instance `i-07c7e0fa7bc7395cc` at `3.12.107.117` remains historical context below; it was not changed during this rollout. Next: open ReturnFlow on the new IP and present `DEMO-1001` or another seeded order. After a restart, use the five start/health commands in **Cold-start TL;DR**.

Last updated: 2026-10-22 (America/Los_Angeles)

This file is the durable handoff record for the project. Update it whenever a
decision is made, a task is completed, or the next action changes so work can
resume safely after VS Code or the chat session is closed.

## Cold-start TL;DR

This is an existing, running environment—not a rebuild. Read this section and
**Immediate next step** first; use `README.md` only when more operational detail
is needed.

- Edit only the Windows repository. WinSCP mirrors it one way to
  `/home/ec2-user/langchain/product-returns`; never edit mirrored source on the
  host because WinSCP can overwrite it.
- Execute only on AWS Linux. Connect as `ec2-user` to `3.23.64.12` with
  PuTTY/Plink, the `.ppk` and pinned fingerprint in **Non-negotiable environment
  rules** below. Do not use PowerShell/OpenSSH for SSH.
- The existing host has Python 3.11, the virtual environment, dependencies,
  database, migrations through `013`, policy vectors, demo seed, and graph
  version `8`. Do not recreate any of them merely because the editor restarted.
- Secrets are in ignored `keys.sh` and AWS-only `api-key.sh`. Never print or
  copy their contents into chat, documentation, logs, or Git.
- To recover the running demo after a host restart:

  ```bash
  cd /home/ec2-user/langchain/product-returns
  bash scripts/start_observability_stack.sh
  bash scripts/start_returnflow_api.sh
  bash scripts/start_presentation.sh
  bash scripts/check_observability_health.sh
  bash scripts/check_returnflow_runtime.sh
  ```

- ReturnFlow is `http://3.23.64.12:3002`; Grafana is
  `http://3.23.64.12:3001`.
- The presenter-visible payment-provider-success failure is implemented.
  Select it on eligible `DEMO-1001`, inspect the stopped run, and resume with
  a new worker to show one refund, two provider requests, and zero duplicates.

## Resume here after reconnecting

Current handoff snapshot on 2026-10-22:

- Work only in the local Windows repository; WinSCP mirrors those files one way
  to `/home/ec2-user/langchain/product-returns`. Execute commands only on the
  AWS host.
- SSH automation must use PuTTY/Plink with the pinned host fingerprint recorded
  below. Do not use PowerShell/OpenSSH for SSH.
- The AWS host has Python 3.11.16 and the project virtual environment at
  `/home/ec2-user/.venvs/product-returns`. All pinned packages in
  `requirements.txt` are installed; imports and `pip check` succeed.
- The current new EC2 instance has 4 vCPU, 15 GiB RAM, and approximately 247
  GiB free disk before image pulls. Its public IP is `3.23.64.12`; its new SSH
  host fingerprint is recorded below. The previous instance's unrelated
  Grafana and Prometheus listeners are not present on this host.
- CockroachDB database `product_returns` and SQL user
  `product_returns_app` exist. The database owner/migration identity is `ron`.
- The database was created fresh on the new cluster. Migrations `001`
  through `013` have been applied successfully. Migration `010` extends the
  existing `node_attempts` audit table with live-journey input and duration
  data; it does not create a competing node-event table. Migration `012` adds
  the durable one-shot presenter failure plan.
- The database contains 23 tables: 19 application-owned and 4 LangGraph-owned.
  `product_returns_app` has exactly `SELECT`, `INSERT`, `UPDATE`, and `DELETE`
  on every table (92 table-grant rows), plus database `CONNECT` and schema
  `USAGE`. Future-table default privileges are also verified.
- A customer-facing Next.js application now exists in `presentation/`. It calls
  the live FastAPI/LangGraph runtime through server-side proxy routes, presents
  a database-backed selector for all seven demo orders, renders persisted
  per-node progress and I/O, quotes
  verified policy evidence, and performs the real durable approval pause and
  resume. The payment boundary remains a deterministic demo provider.
  Next.js 16.4.2 has zero `npm audit` findings, and both strict type checking
  and a production build passed on AWS. It remains assigned port 3002;
  Grafana occupies port 3001. ReturnFlow is currently running as
  a PID-managed background process and is publicly reachable at
  `http://3.23.64.12:3002`; both the host-local and Windows-desktop HTTP
  checks returned status 200. Use `scripts/start_presentation.sh` and
  `scripts/stop_presentation.sh` to manage it safely. Runtime logs are stored
  outside the synchronized repository at
  `/home/ec2-user/.local/state/product-returns/presentation/server.log`.
- The private FastAPI process is bound only to `127.0.0.1:8010` and is managed
  by `scripts/start_returnflow_api.sh` / `scripts/stop_returnflow_api.sh`. Its
  dispatcher claims due work with renewable leases and safely resumes expired
  or manager-approved runs. Its log is outside the synchronized repository at
  `/home/ec2-user/.local/state/product-returns/api/server.log`.
- Live automatic-refund, approval/resume, policy-denial, and public-proxy reset
  tests all pass, as do the focused fraud-only, AI activation-conflict, and
  grounded product-safety acknowledgement paths. Reset is restricted to
  synthetic `returnflow-` threads,
  refuses active runs, removes their checkpoints, and restores reserved or
  refunded demo quantity so every selected order can be replayed.
- Graph version `8` adds a presenter-controlled, durable one-shot failure at
  any parallel evidence node. A stopped run has no worker lease and no
  automatic retry time. Resume claims lease generation 2 and uses a pinned
  saver adapter to read the exact published checkpoint while allowing
  LangGraph to apply successful sibling pending writes. The focused AWS proof
  failed `assess_fraud`, kept order/policy at one attempt each, retried only
  fraud, and completed one refund. Exact run-scoped inspection SQL is exposed
  in the UI/API for workflow, attempts, audit, checkpoints, writes, and blobs.
- Migration `013` adds the payment one-shot mode to the same durable plan.
  `issue_refund` stops after the demo provider records its refund and before
  local completion. Presenter resume uses a new lease generation and the same
  idempotency key. The live proxy proof found one provider refund, two
  requests, zero duplicates, and no background retry. The UI and nine-query
  SQL pack expose both sides of the payment boundary.
- `migrations/002_business_schema.sql` and
  `migrations/003_workflow_schema.sql` have passed an initial design review and
  executed successfully against the cluster.
- The customer-facing policy source is
  `policies/standard-return-policy-v1.md`, version 1.0. Its stable clause IDs
  support attributable chunking, embedding, retrieval, and verification.
- Product category is stored on both the catalog product and its order-item
  snapshot; `order_items.activated_at` records activation. These facts support
  deterministic gift-card and activated-phone policy exclusions.
- Fraud assessment is checkpointed graph state, not a `fraud_signals` business
  table. Summaries/provenance also belong in `node_attempts` and `audit_events`.
- LangGraph's package-owned checkpoint tables have been created once as `ron`
  through `CockroachDBSaver.setup()`. Normal application execution must use
  `product_returns_app` and must not call `setup()`.
- `README.md` is the operational AWS-host runbook. It covers environment
  activation, configuration load order, all thirteen repository migrations, checkpoint
  setup, seed data, policy ingestion, retrieval validation, grants, and a
  complete non-destructive rebuild sequence.
- `keys.sh` is intentionally synchronized to AWS but ignored by Git. Linux-only
  `api-key.sh` is also ignored and exports `OPENAI_API_KEY`. Both contain
  secrets and must never be printed, committed, or copied into this file.
- `scripts/check_openai_environment.sh` was run through a fresh Plink session
  and confirmed that `OPENAI_API_KEY` is non-empty and exported to child
  processes. No part of the key was printed.
- `scripts/setup_langgraph_checkpoint.py` completed successfully as `ron` and
  created `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, and
  `checkpoint_migrations`. Migration `001` was rerun afterward.
- `scripts/smoke_test_checkpoint.py` runs a deterministic one-node
  graph using `CRDB_APP_URL`. It does not call `setup()`, verifies checkpoint
  write/read/list behavior, and cleans up its temporary thread after success.
- `scripts/run_checkpoint_smoke_test.sh` supplies the repeatable AWS-host
  activation/configuration wrapper. The smoke test ran successfully through
  Plink as `product_returns_app`, verified three checkpoints, and cleaned up its
  temporary thread.
- `migrations/004_demo_seed.sql` was validated and applied as
  `product_returns_app`. It loaded 35 expected fixture rows spanning customers,
  products, orders, policy data, and historical returns.
- `langchain-openai` 1.7.2 is pinned and installed. The OpenAI
  `text-embedding-3-small` model produces the configured 1,536-dimensional
  vectors.
- Policy ingestion parsed and verified the eight identified Markdown sections,
  then stored eight deterministic chunks in namespace
  `standard-returns:1.0`. A 3/3 semantic retrieval smoke test found the expected
  gift-card, manager-review, and 30-day clauses and verified each citation
  against relational policy data.
- Typed `ReturnWorkflowState` and the structured request-classification node are
  implemented. The AWS smoke test correctly classified refund, complaint, and
  ambiguous messages and extracted a grounded “has not been activated” claim,
  verified the resulting CockroachDB checkpoints, and deleted its temporary
  threads.
- The evidence round is implemented. Refund classifications fan out to
  independent `lookup_order`, `retrieve_policy`, and `assess_fraud` nodes. Each
  writes a separate typed state field and is wrapped by the existing metrics,
  traces, and structured event instrumentation.
- Policy evidence is accepted only after every vector result matches an active
  relational clause, policy/version, document/source hash, authoritative IDs,
  embedding model, and dimensions. Fraud assessment uses explicit demo rules
  over account status and prior refunded returns; it is not a fraud verdict.
- `scripts/explain_evidence_queries.sh` passed for all three relational access
  paths. `scripts/run_evidence_round_smoke_test.sh` deliberately failed the
  fraud node once and proved targeted retry: order and policy each ran once,
  fraud ran twice, all three results survived in the final CockroachDB-backed
  state, four checkpoints were present, and Prometheus captured the activity.
  Post-run backend validation found five recent Tempo traces, 28 Loki events,
  all three evidence success metrics, and the deliberate fraud failure metric.
- Source-controlled graph version `8`, its semantic manifest/signature guard,
  atomic run claim/reclaim, daemon heartbeat, fenced checkpoint publication,
  fenced release, and explicit published-checkpoint resume configuration are
  implemented in `graph_version.py` and `workflow_runs.py`. Deployment config
  only asserts the expected version; it is not authoritative.
- The live workflow-lease smoke test passed: omission of `graph_version` was
  rejected, an active generation blocked a competitor, background heartbeat
  kept generation 1 alive, stopping it allowed generation 2 to reclaim the
  run, and stale generation 1 could no longer publish. Temporary rows were
  removed. All production ownership statements passed EXPLAIN.
- The ownership layer is now integrated with the real checkpoint-backed
  classification/evidence graph in `workflow_worker.py`. It captures the final
  checkpoint event emitted by the specific invocation with synchronous
  durability, avoiding any unqualified-latest-checkpoint race.
- The AWS worker recovery smoke test passed through the complete happy path.
  Worker A ran the OpenAI classifier, all three parallel evidence branches,
  deterministic decision, `reserve_return_items`, and `issue_refund`, then
  published its exact terminal checkpoint. After simulated process death and
  lease expiry, Worker B reclaimed
  generation 2, loaded that checkpoint, reran zero graph nodes, and atomically
  finalized the refund. Cleanup removed all temporary workflow/provider data.
- Graph version `2` adds the deterministic `decide_return` node after the three
  evidence branches. Its seven tested paths cover automatic approval, the
  over-$500 threshold, fraud review, gift-card exclusion, activated-phone
  exclusion, an expired return window, and a missing order. Decisions contain
  stable reason codes, explanations, calculated amounts, verified policy
  citations, and the facts used.
- `decision_store.py` commits the workflow transition, return-request status,
  optional manager approval, lease release, and complete audit event in one
  short CockroachDB transaction with full-transaction retry for serialization
  failures. Database smoke tests proved both an `OUTSIDE_RETURN_WINDOW`
  rejection and a `REFUND_OVER_MANAGER_LIMIT` durable approval pause. All five
  SQL paths passed EXPLAIN; UUID primary-key or existing run-scoped index access
  keeps each operation narrowly targeted.
- Graph version `3` adds the real `await_manager_approval` LangGraph interrupt.
  `manager_decision.py` records an approval or rejection without a live graph;
  the later worker loads that row and supplies it through `Command(resume=...)`
  to the exact published checkpoint. The two-path AWS smoke test proved that
  the waiting run had no lease and was not claimable, generation 2 resumed
  without rerunning evidence. That original graph-version-3 proof queued
  `issue_refund`; the graph-version-4 regression now continues an approval
  through a completed refund. Rejection still ends as `rejected`, graph state
  retains the response, and each path has three ordered audit events.
- Graph version `4` adds the observable `issue_refund` node and typed
  `refund_result`. Its stable provider key is
  `product-returns:<run_id>:refund:v1`. Provider work occurs outside the local
  CockroachDB transaction, and `commit_refund_completion()` atomically finalizes
  the workflow, request, and full decision/refund audit record under the lease
  fence. The focused AWS test failed once immediately after provider success:
  the retry produced two requests but only one provider refund ID, while local
  attempt 1 became `retryable_failure` and attempt 2 succeeded. All production
  refund SQL passed EXPLAIN. Suggested broad covering indexes were not added;
  plans use UUID/unique point lookups or existing run-scoped indexes and these
  demo tables are small.
- The approval smoke test now traverses the final node too: manager approval
  resumes generation 2, issues the refund, and finishes `completed/refunded`;
  manager rejection finishes `rejected` without a provider refund.
- Graph version `5` adds concurrency-safe, per-order-item quantity protection.
  `return_item_capacity` tracks purchased/reserved/refunded units and
  `return_item_allocations` ties a reservation to one request. Eligible graph
  paths reserve before approval/refund; manager rejection releases quantity;
  refund completion permanently consumes it. Two simultaneous requests for the
  same two units produced exactly one reservation and one conflict. Release
  made the units reusable; refund made them unavailable; the later conflict
  became a fenced, audited business rejection without a provider call. All new
  SQL passed EXPLAIN, and the critical allocation reads use the covering
  `return_allocations_by_request_item` index without an index join. Final
  version-5 validation reported signature
  `31d5fc1a0e63767c31c790853c25e7d2042031f693922ae21d56d28b5a30c1d3`,
  22 tables, 88 runtime CRUD grants, and zero leftover workflow, refund,
  provider-refund, active-reservation, or capacity-violation rows.
- Graph version `6` adds strict structured extraction of device-activation
  claims. Model-provided supporting text must occur verbatim in the original
  message before deterministic rules compare it with `activated_at`. The live
  `DEMO-1004` proof extracted “has not been activated,” found the conflicting
  database timestamp, recorded `ACTIVATION_STATUS_CONFLICT`, paused durably,
  resumed after approval, and issued exactly one idempotent refund. Its graph
  signature is
  `bb98109d3596db4f6d741bfe2ab408f4009da7dce8b3481d6a92874888ded517`.
  A transient `ReadWithinUncertaintyIntervalError` discovered during polling
  led to bounded full-transaction retries in `load_run_snapshot()`; the rerun
  and all five existing public API regressions passed.
- Graph version `7` adds strict structured extraction of potential product-
  safety concerns with deterministic verbatim grounding. The decision records
  a separately labeled `POTENTIAL_PRODUCT_SAFETY_CONCERN` insight and truthful
  customer acknowledgement without changing eligibility, approval, or refund
  routing. `DEMO-1001` now demonstrates overheating/property-damage awareness;
  the UI shows the source quote and says it was recorded for product-safety
  follow-up without claiming external notification. The focused public API
  proof is `scripts/run_safety_acknowledgement_api_smoke_test.sh`; no schema
  migration is required because the new fields live in checkpoint/audit JSON.
- The classifier uses configurable OpenAI `gpt-6-luna` with reasoning effort
  `none`. Every instrumented node now emits low-cardinality Prometheus metrics,
  OpenTelemetry spans with input/output events, and credential-redacted JSON
  logs correlated by run, thread, trace, and span IDs.
- The current end-to-end workflow smoke test now initializes OTLP/log export,
  exposes port 8000 only until Prometheus confirms its scrape, and then exits.
  Stable run-derived trace correlation keeps classification, all three parallel
  evidence nodes, and `decide_return` in one Tempo trace even when LangGraph
  executes nodes on different threads. The live verifier confirmed five spans
  in trace `09ddef8e9e1ddc8a0e19f1d33bd4defd`, all five Prometheus node metrics,
  the Loki decision event, and the provisioned Grafana dashboard. The new host
  independently passed the same verifier with five node spans and metrics.
- The isolated Product Returns observability stack is running with pinned
  Grafana 13.2.2, Prometheus 3.13.3, Tempo 3.1.0, Loki 3.7.8, and Alloy 1.20.1.
  All five readiness endpoints pass and all containers have zero restarts.
  Grafana is reachable at `http://3.23.64.12:3001`. The provisioning API
  confirms the **Product Returns — Graph Operations** dashboard under the
  **Product Returns** folder with UID `product-returns-graph-operations`.
- Product Returns uses port 3001 for Grafana and loopback port 9091 for
  Prometheus, with its own network and named volumes. The previous host's
  unrelated `iam_demo_v2` stack was not copied to this new instance.
- `GRAFANA_ADMIN_PASSWORD` is exported by ignored `keys.sh`, and
  `PRODUCT_RETURNS_OTLP_ENABLED` is `true`. Cockroach Cloud now allows
  `3.23.64.12/32`. The current instrumented classifier passed 6/6, including
  grounded activation and safety extraction. Earlier backend API checks confirmed
  the classifier traces in Tempo, JSON events in Loki, and the provisioned
  Grafana dashboard.

## Project goal

Build a LangChain/LangGraph demonstration that processes product-return
requests as a durable graph workflow. CockroachDB is the system of record for
commerce data, graph state/checkpoints, resumable work, and an audit trail.
The application is hosted on an AWS Linux EC2 host and uses a project-specific
database in CockroachDB Cloud.

## Non-negotiable environment rules

- **Nothing is executed on this Windows desktop.** The local directory is only
  the source-code repository and the home of this context file.
- Ron runs WinSCP **Keep remote directory up to date** as a one-way
  local-to-remote deployment mirror. Local file changes are automatically
  copied to the AWS Linux host. Nothing is copied from AWS back to Windows.
  Therefore, edit repository files locally only; remote changes within the
  mirrored directory can be overwritten or removed by WinSCP. Runtime state,
  secrets, virtual environments, logs, and generated artifacts belong outside
  the mirrored directory unless they originate from the local repository.
- Use **PuTTY tooling** for SSH access. For automated/non-interactive commands,
  use PuTTY's `plink.exe`; do not initiate SSH through PowerShell/OpenSSH.
- AWS host IP: `3.23.64.12` (instance `i-05c2574bc30900e89`)
- PuTTY private-key path (reference only; never copy or commit the key):
  `C:\Users\RonNollen\Documents\Key-Pairs\nollen-cockroach-revenue-us-east-2-kp01.ppk`
- SSH username: `ec2-user`
- The server's SSH host key was independently verified from an existing PuTTY
  session as
  `ssh-ed25519 255 SHA256:+S3ZyxZany8Kwni2XIHDI7phGA2Avf+OWGC4TRDghSU`.
  Plink connections must pin this exact fingerprint. Never bypass host-key
  verification.
- Do not commit database passwords, API keys, SSH keys, or credential-bearing
  connection strings. Store runtime secrets on the AWS host using environment
  variables or an approved AWS secret store.
- `config.sh` is the committed source for non-secret environment configuration.
  `keys.sh` is copied to AWS by WinSCP but ignored by Git and holds database
  secrets. Linux-only `api-key.sh` is ignored by Git and holds the OpenAI API
  key. Do not inspect, print, log, or commit either file's values.

## Current status

- Project requirements and the intended graph behavior have been captured.
- An authenticated, read-only Plink inventory has been completed successfully.
- A Python 3.11 virtual environment was created successfully at
  `/home/ec2-user/.venvs/product-returns`. The pinned core dependencies are
  installed and their principal imports succeed. Policy ingestion, retrieval,
  and complete product-return graph workflows have run successfully on AWS.
- `requirements.txt` now pins the reviewed core runtime packages: LangChain
  1.4.1, LangGraph 1.2.12, `langchain-cockroachdb` 0.4.0,
  `langchain-openai` 1.7.2, Psycopg 3.3.6 with its binary distribution, and
  `psycopg-pool` 3.3.3, plus FastAPI 0.156.1 and Uvicorn 0.54.0. AWS-host
  resolver checks and installation completed without conflicts; principal
  imports and `pip check` succeeded.
- The `product_returns` CockroachDB database and `product_returns_app` SQL user
  exist. Migrations `001` through `013` have been executed successfully.
  The 19 application tables exist; direct application `CONNECT`, schema
  `USAGE`, CRUD on every application table, and future-table default privileges
  are verified. Broad public `CONNECT` and schema `CREATE` remain removed.
- The deterministic fixtures are loaded: 3 customers, 5 products, 7 orders,
  7 order items, 1 policy, 8 clauses, 3 historical returns, and 3 return items.
- The source policy has been embedded into 8 verified `policy_chunks` rows in
  namespace `standard-returns:1.0`. A three-query semantic retrieval smoke test
  found and verified the expected clause for every query.
- Python 3.11 is confirmed as the application runtime. The current
  `langchain-cockroachdb` integration supports Python 3.10 or newer.
- The cluster endpoint, project database, owner, application identity, and
  server version are known. The credential previously exposed in chat has been
  rotated.

## Current AWS host inventory

Observed on 2026-10-22 through Plink with the verified new host key:

- Hostname: `ip-192-168-2-142.us-east-2.compute.internal`
- Instance: `i-05c2574bc30900e89`, `t3a.xlarge`, `x86_64`
- OS: Amazon Linux 2023.12.20261021
- CPU/memory: 4 vCPU, 15 GiB usable RAM
- Root filesystem: 250 GiB total, 247 GiB free before deployment downloads
- Python 3.11.16; project virtual environment at `/home/ec2-user/.venvs/product-returns`
- Git 2.50.1; CockroachDB CLI 26.2.7; Docker 25.0.16; Docker Compose 5.6.0; Node.js 24.21.0/npm 11.19.0
- WinSCP mirrors the Windows source to `/home/ec2-user/langchain/product-returns`.

## Previous AWS host inventory (historical)

Observed read-only on 2026-10-16 through Plink with the verified host key:

- Hostname: `ip-192-168-1-16.us-east-2.compute.internal`
- Platform: Amazon EC2, `t3a.small`, `x86_64`
- OS: Amazon Linux 2023.12.20261014
- Kernel: 6.1.188-233.393.amzn2023.x86_64
- Root filesystem: 500 GB total, 190 GB used, 311 GB available (38% used)
- `python3`: `/usr/bin/python3`, Python 3.9.25, with no pip module
- `python3.11`: `/usr/bin/python3.11`, Python 3.11.16
- `pip3`: pip 26.1.1 associated with Python 3.11 under
  `/home/ec2-user/.local/lib/python3.11/site-packages`
- Git: 2.50.1
- CockroachDB CLI: `/usr/local/bin/cockroach`, version 26.1.0 CCL
- WinSCP is configured and running with the confirmed remote project directory
  `/home/ec2-user/langchain/product-returns`. The two pre-existing files in the
  parent `/home/ec2-user/langchain` directory remain out of project scope.

The `python3`/`pip3` interpreter mismatch must be resolved before installing
project packages. Use an explicit interpreter and its `python -m pip` inside a
project virtual environment rather than relying on the ambiguous `pip3` command.

## CockroachDB cluster inventory

Verified from the new AWS host on 2026-10-22:

- Endpoint: `nollen-langgraph-demo-35081.j77.cockroachlabs.cloud:26257`
- Owner and migration SQL user: `ron`
- Administrative connection database: `defaultdb`
- Server version: CockroachDB CCL 26.2.7
- Client version: CockroachDB CCL 26.2.7
- TLS mode used successfully: `verify-full` with the system CA bundle
- Compatibility: server 26.2.7 exceeds the `langchain-cockroachdb` documented
  minimum of CockroachDB 25.4.
- Project database: `product_returns`, owned by `ron`
- Project application user: `product_returns_app`
- Project database primary region: `aws-us-east-2`
- Project database regions: `aws-us-east-2`, `aws-us-east-1`, `aws-us-west-2`
- Project database survival goal: zone failure
- Initial locality recommendation: use regular regional tables in the primary region
  for commerce, workflow, approval, and refund data because the application host
  has a single write home in `aws-us-east-2`. Evaluate `GLOBAL` locality only
  for read-mostly policy reference data after the baseline works.

Never store a credential-bearing connection string in this repository. The
password previously pasted into chat was rotated. The current owner credential
is supplied through `CRDB_RON_PASSWORD`; a sanitized manual-login form is:

```bash
cockroach sql --url "$CRDB_RON_URL"
```

Do not print or record the variable's value. Create a separate least-privilege
application identity rather than running the application as the existing `ron`
user.

`config.sh` holds non-secret database settings and constructs connection URLs
after `keys.sh` supplies the database secrets. Linux-only `api-key.sh` exports
`OPENAI_API_KEY`. Source them in this order: `keys.sh`, `api-key.sh`, then
`config.sh`; never log the resulting URLs or API key.

## Initial technical direction

- **Application language:** Python is confirmed because LangGraph and LangChain
  have strong Python support. "Postgres" is the database wire protocol/SQL
  dialect, not the application language.
- **Workflow framework:** LangGraph for explicit state, parallel nodes,
  checkpointing, retries, interrupts, and resume-after-approval behavior;
  LangChain components only where they add value.
- **Database:** CockroachDB Standard through its PostgreSQL-compatible wire
  protocol. Use CockroachDB-compatible SQL and UUID primary keys.
- **Policy embeddings:** OpenAI `text-embedding-3-small` at its default 1,536
  dimensions, stored in CockroachDB as `VECTOR(1536)`. The Markdown policy and
  relational clauses remain authoritative; vectors are a derived search index.
- **Deployment:** application process and all developer commands run only on
  the AWS Linux host. The Windows workspace supplies synchronized source files.
- **Payment integration:** begin with a deterministic fake provider for the
  demo, enforcing a unique idempotency key. A real provider can replace it
  behind the same interface later.

Except where marked provisional, these are accepted implementation decisions.

## Intended workflow

1. **Classify request**
   - Decide whether the incoming message is a return/refund request or another
     intent such as a complaint.
   - Non-return requests leave the refund path with a clear terminal outcome.

2. **Gather evidence in parallel**
   - Look up the order and requested items.
   - Retrieve the applicable return-policy clause (initial rule: within 30 days).
   - Check account/order fraud signals.
   - Persist each node's output independently. If one node fails, retry only
     that node; do not discard successful sibling results.
   - Verify that policy retrieval produced a real, attributable policy clause.
     A failed verification retries/fails that narrow node instead of allowing
     unsupported policy text into the decision.

3. **Determine eligibility and approval**
   - Combine order facts, verified policy facts, fraud signals, and calculated
     refund amount.
   - Fraud or policy failures must produce an explicit review/denial outcome;
     exact business rules are still to be specified.
   - A refund over `$500.00` requires manager approval. Boundary behavior at
     exactly `$500.00` must be confirmed (current wording implies no approval
     at exactly $500).

4. **Durable manager pause, when required**
   - Persist the complete checkpoint and next-node information.
   - Record the run as waiting for approval, then allow the process to exit
     completely. No thread, request, worker, transaction, or in-memory graph is
     kept open.
   - Manager approval or rejection is an ordinary external event, not an error.
     On receipt, load the checkpoint, append the decision to state/audit history,
     and resume from the next eligible node.

5. **Issue refund or finish without one**
   - Approved or auto-approved requests advance to `issue_refund`.
   - Rejected/ineligible requests end with a recorded reason.
   - The refund call uses a stable idempotency key derived from the logical
     refund identity (provisional format: `return:<run_id>:refund`). The payment
     provider and local database must reject reuse for a different operation
     and return the original result for an exact retry.

## Durability and correctness requirements

- A run is a durable chain of checkpoints, not a long-lived process.
- The latest checkpoint records the full resumable state and which nodes are
  due next.
- Append-only checkpoint/audit history must show what the system knew, what it
  decided, and why at every step. Do not overwrite the only historical copy.
- Node attempts require stable identities and statuses so a failed node can be
  retried without repeating completed siblings.
- Side-effecting nodes use application-level idempotency. Database transaction
  retries alone do not make an external payment call safe.
- Money uses exact `DECIMAL` values plus an ISO currency code, never floating
  point.
- Timestamps use `TIMESTAMPTZ`; entity keys use UUIDs to avoid distributed
  sequential-key hotspots.
- State transitions should use transactions and optimistic version checks (or
  equivalent compare-and-set behavior) to prevent two workers from advancing
  the same run simultaneously.
- Store structured facts and provenance separately from model-written prose.
  Every policy result should identify the policy document/version and clause.
- External input, model output, node errors, approval identity/timestamp, and
  refund-provider responses must be auditable with appropriate redaction.

## Data model drafts

The current schema is recorded in `migrations/002_business_schema.sql` and
`migrations/003_workflow_schema.sql`; both have been reviewed and executed.

- `customers` — customer/account identity and aggregate status.
- `products` — catalog entries/SKUs used by order items.
- `orders` — customer order, purchase time, currency, and order status.
- `order_items` — product, quantity, unit price, and refundable quantities.
- `return_policies` — versioned policy documents with validity dates.
- `policy_clauses` — attributable clauses used by retrieval and verification.
- `policy_chunks` — connector-compatible document chunks, citation metadata,
  and `VECTOR(1536)` values used for semantic policy retrieval. The table
  contains 8 verified chunks for policy version 1.0.
- `return_requests` — the customer's request and business-level return status.
- `return_items` — requested items, quantities, and calculated amounts.
- `workflow_runs` — one graph run, latest status/version, correlation data,
  graph compatibility version, and renewable worker lease. `lease_generation`
  is a per-run fencing counter, never a global sequence or indexed key.
- LangGraph CockroachDBSaver tables — package-owned immutable checkpoints with
  serialized state and next-node information. Create these once with the
  saver's `setup()` method as `ron`; do not duplicate or hand-maintain them.
- `node_attempts` — per-node attempt status, inputs/outputs, error, and timing.
- `approval_requests` — durable pending/approved/rejected manager decisions.
- `refunds` — logical refund and unique idempotency key.
- `refund_attempts` — provider attempts and sanitized responses for auditing.
- `audit_events` — append-only business and workflow event trail.

CockroachDB rules for the eventual schema: every table gets an explicit primary
key; prefer UUID keys; use explicit constraints and foreign keys; add indexes
from observed access paths; use `JSONB` only for genuinely flexible graph/model
payloads rather than hiding core relational business data.

## Open decisions and required inputs

1. Decide whether graph roles beyond the completed classifier should also use
   OpenAI `gpt-6-luna` or use a different model. Embeddings remain OpenAI
   `text-embedding-3-small`; the API key is exported by Linux-only, ignored
   `api-key.sh`.
2. Define fraud outcomes: automatic denial, mandatory review, or a risk-score
   threshold; also define what happens if the fraud service is unavailable.
3. Confirm the `$500` boundary, partial-return rules, shipping/tax/restocking
   treatment, and whether multiple refunds may exist for one return.
4. The current demo accepts manager decisions through the ReturnFlow API/UI;
   decide what authentication and authorization a production approval channel
   would require.
5. Decide retention/redaction requirements for customer, model, and audit data.

## Planned implementation phases

### Phase 1 — confirm and inspect

- Confirm the open decisions needed for a minimal demo.
- Connect to AWS with PuTTY/Plink only and inventory Amazon Linux version,
  architecture, installed tools, and synchronized repository path.
- Inspect the CockroachDB Standard cluster without changing it.

### Phase 2 — scaffold the host environment

- Install the selected Python runtime and isolated project environment on AWS.
- Add pinned LangGraph/LangChain and CockroachDB/PostgreSQL-driver dependencies.
- Configure secrets on AWS without placing them in the synchronized repository.
- Add health/configuration checks.

### Phase 3 — database foundation

- Create the project database and least-privilege application role.
- Add versioned CockroachDB migrations for commerce, policy, fraud, workflow,
  approvals, refunds, and audit records.
- Seed deterministic demo orders, policies, and fraud scenarios.

### Phase 4 — durable graph

- Implement classification, the three parallel evidence nodes, policy verifier,
  decision routing, durable approval interrupt/resume, and refund node.
- Persist independent node results/checkpoints and targeted retry state.
- Enforce concurrency control and refund idempotency.

### Phase 5 — verification and demo

- Test happy path, non-return intent, policy failure/retry, fraud outcomes,
  manager approval/rejection, full process shutdown/resume, duplicate delivery,
  concurrent resume, and refund failure after provider success.
- Demonstrate the checkpoint history and audit trail for each scenario.

## Immediate next step

Open `http://3.23.64.12:3002` from the presenter browser and run `DEMO-1001`.
The new host's automated live payment proof has passed. To show it manually,
choose **Fail after payment-provider success**, submit,
inspect the stopped provider refund and released lease, then select **Resume
with a new worker**. The final panel shows one refund issued, two provider
requests, zero duplicate payments, the stable key and provider ID, local node
and refund attempts, audit events, and Grafana links. **Copy database
inspection SQL** provides nine run-scoped read-only queries. The repeatable
proxy proof is `bash scripts/run_payment_resilience_api_smoke_test.sh`.

No further implementation is required for this increment. Possible later
tasks are direct run/trace navigation and boot-time service startup. The
deterministic provider remains the payment boundary; graph version stays `8`
because topology, checkpoint state, and node contract did not change.

The seed, vector ingestion, and retrieval foundation are complete. Policy
quotes carry document title, policy version, section heading, and clause
identifier, and the smoke test verifies them against authoritative relational
policy data before use. Page numbers are intentionally not required.

Operational instructions are maintained in `README.md`, including host-only
execution, virtual-environment activation, configuration load order, all thirteen
repository migrations, and the separate package-owned LangGraph checkpoint
setup.

## Change log

- 2026-10-22 — Deployed the complete demo to new EC2 instance `i-05c2574bc30900e89` and a new CockroachDB cluster. Verified and pinned its SSH host key; installed the host toolchain; added the new IP to the cluster allowlist; created the database and app login; applied all schema, checkpoint, seed, capacity, and policy steps; started and verified observability, API, and presentation. Added explicit system CA configuration after the fresh host revealed that libpq lacked a per-user root certificate. Corrected the rebuild order so migration `008` backfills historical allocations after seeding. All live API smoke paths and the observability verifier passed.
- 2026-10-21 - Implemented the presenter-visible provider-success/worker-
  failure story. Migration `013` extends the durable one-shot failure plan;
  the provider unique-key constraint remains intact. ReturnFlow shows the
  stopped and recovered payment ledger, local attempts, audit, copied SQL,
  and trace/log links. The live proxy proof found one provider refund from two
  requests and no automatic retry. Existing evidence and refund regressions,
  nine SQL EXPLAIN plans, TypeScript check, production build, and service
  health checks passed. The synthetic fixture was restored.

- 2026-10-21 - Added cold-start TL;DR instructions to this handoff and the
  runbook, explicitly separating an existing-host restart from a clean rebuild.
  Recorded the next increment as a presenter-visible failure after provider
  refund success, with the acceptance proof: one refund, two provider requests,
  and zero duplicate payments. No payment-failure UI behavior was implemented
  in this documentation-only step.

- 2026-10-21 - Added graph version `8` and the controlled resilience
  demonstration. A presenter can inject a durable one-shot failure into order,
  policy, or account evidence. The run publishes a recovery checkpoint,
  releases its lease with no automatic retry, and resumes only on presenter
  action under a new generation. `PinnedResumeCockroachDBSaver` retains the
  exact application-published checkpoint fence while allowing LangGraph to
  apply successful sibling pending writes. The focused live proof kept the two
  successful siblings at one attempt, retried only `assess_fraud`, and issued
  one refund. ReturnFlow can copy seven exact-UUID read-only inspection queries;
  Grafana adds injected-failure, recovery-checkpoint, and resumption counters.
  All seven queries passed CockroachDB `EXPLAIN`; the complete existing API
  regression suite, dashboard validation, and observability health checks pass.

- 2026-10-20 — Added graph version `7` and the grounded customer-safety insight
  path. OpenAI extracts a typed concern and exact supporting quote; application
  code verifies the quote before state accepts it. The insight is checkpointed,
  audited, shown in ReturnFlow, and acknowledged after refund, while the
  deterministic return decision and routing remain unchanged.

- 2026-10-20 — Added graph version `6` to demonstrate useful, bounded AI.
  OpenAI structured output extracts an explicit activation claim and exact
  supporting quote; application code verifies that quote against the request,
  and deterministic rules compare it with authoritative `activated_at` data.
  `DEMO-1004` now routes the resulting `ACTIVATION_STATUS_CONFLICT` to durable
  human review instead of allowing AI to override the record or automatically
  denying the customer. The complete approval/refund proof, four-path
  classifier test, eight-path decision test, five existing API regressions,
  strict TypeScript check, and production build pass. Snapshot polling now
  retries full CockroachDB read transactions after a transient serialization
  error exposed during the first proof.

- 2026-10-20 — Replaced the three outcome-labeled story buttons with a clearly
  marked presenter order selector populated from the live CockroachDB fixtures.
  Added rerunnable migration `011` for `DEMO-1007`, an otherwise eligible Bob
  order whose restricted-account and prior-refund signals alone produce risk
  score 90 and manager review. The focused public-API smoke test approved the
  checkpointed run and completed exactly one refund; all new SQL passed
  `EXPLAIN`, strict TypeScript checking and the production build passed, and
  both services were restarted successfully.

- 2026-10-20 — Replaced ReturnFlow's browser-timed prototype with a live
  FastAPI/LangGraph runtime and CockroachDB dispatcher. Added atomic submission,
  lease-based recovery, real approval/resume, durable per-node I/O and timing,
  same-origin Next.js proxy routes, and safe repeatable-demo reset. Automatic
  refund, manager approval, policy denial, and reset/replay smoke tests pass
  through the live services. Migration `010`, all API/reset EXPLAIN plans,
  TypeScript checking, and the production Next.js build pass on AWS.

- 2026-10-20 — Fixed the manager-approval proxy after live browser testing
  found that Next.js did not publish the nested `manager-decision` route beneath
  a sibling dynamic route. Consolidated dynamic return operations into a
  catch-all route, changed the approval regression wrapper to exercise port
  3002, and proved the previously paused `$700.92` run accepted approval,
  resumed as lease generation 2, and completed exactly one refund.

- 2026-10-20 — Corrected terminal presentation copy for non-refund intents.
  Complaints and other messages now show that no return/refund was requested,
  while true business denials derive their explanation from the persisted
  decision and reason code. Added last-run restoration across browser refresh
  and a live complaint regression proving that only classification ran and no
  order, policy, fraud, approval, or refund work was created.

- 2026-10-20 — Added the ReturnFlow customer-facing Next.js presentation
  scaffold, based on the strongest interaction and visual patterns from the
  successful NextEra demo. It includes seeded scenario controls, a natural
  language return experience, animated graph progression, parallel evidence,
  policy quotation, per-node I/O, durable approval storytelling, and outcome
  screens. Next.js was advanced to patched version 16.4.2; `npm audit`, strict
  TypeScript checking, and the production build pass on AWS. This entry records
  the original visual slice; the later entry above records its live integration.

- 2026-10-20 — Added graph version `5`, migration `008` item-capacity and
  allocation ledgers, migration `009` covering allocation index, the observable
  `reserve_return_items` node, release-on-rejection, consume-on-refund, and an
  audited quantity-conflict terminal path. Concurrent AWS testing proved one
  winner for simultaneous requests, reusable released units, and permanently
  consumed refunded units. All new SQL passed EXPLAIN.

- 2026-10-20 — Added graph version `4` and the terminal, observable,
  idempotent `issue_refund` node; added the provider-side demo ledger,
  crash-window retry proof, fenced atomic completion transaction, full
  decision/refund audit event, and end-to-end automatic and manager-approved
  refund tests. Migration `007` and runtime grants are live; all new SQL passed
  EXPLAIN.

- 2026-10-20 — Added graph version `3` with a true LangGraph manager interrupt,
  external manager decision transaction/CLI, exact-checkpoint
  `Command(resume=...)`, and fenced approval-resolution commit. Live approval
  and rejection tests proved a lease-free, unclaimable wait followed by a new
  generation-2 worker; both paths retained manager identity, note, graph state,
  checkpoint lineage, and three ordered audit events. Regression and EXPLAIN
  checks passed.
- 2026-10-20 — Connected the full five-node workflow recovery test to
  Prometheus, Loki, Tempo, and Grafana. Added run-derived trace correlation so
  parallel nodes share one trace ID, plus a backend verifier that starts with
  the latest Loki decision event and proves the same request has all five Tempo
  spans and Prometheus metrics. The verifier passed against the live stack.
- 2026-10-20 — Added graph version `2` with the deterministic return-decision
  node and atomic CockroachDB decision persistence. Seven rule scenarios and
  two database transition scenarios passed. Rejections now retain their exact
  reason, facts, verified policy citations, and checkpoint in `audit_events`;
  manager cases create a durable pending approval. The real crash/reclaim test
  also committed the recovered graph decision without rerunning evidence.
- 2026-10-20 — Integrated renewable ownership with the actual
  checkpoint-backed classification/evidence graph. The worker captures the
  final checkpoint event emitted by its own synchronous graph stream and
  publishes that exact ID under generation/state-version fencing. The AWS
  smoke test simulated death after publication: generation 2 reclaimed the
  run, loaded the published terminal checkpoint, reran no evidence nodes, and
  released successfully. Temporary business and checkpoint rows were cleaned.
- 2026-10-19 — Implemented source-controlled graph identity and durable worker
  ownership. Added a semantic manifest/signature guard, deployment-version
  assertion, explicit version stamping, atomic claim/reclaim, background
  heartbeat, state-version/checkpoint fencing, lease release, and resume config
  pinned to the application-published checkpoint. The AWS smoke test proved
  expiration/reclaim from generation 1 to 2 and rejected the stale worker;
  EXPLAIN passed for all production ownership SQL paths.
- 2026-10-19 — Designed migration `006` for renewable workflow-run leases.
  The design uses UUID-distributed `run_id` rows, a non-indexed per-run INT8
  generation as the stale-worker fencing value, database timestamps for lease
  acquisition/heartbeat/expiry, a graph compatibility version, complete-lease
  constraints, and an expired-run scheduler index. Added repeatable apply,
  inspection, and EXPLAIN wrappers. `graph_version` has no database default:
  migration `006` backfills pre-version rows to `1`, then requires Python to
  supply the version for every new run. The migration and privilege refresh
  completed successfully; schema inspection confirmed a NULL column default
  and all three new CHECK constraints are validated. EXPLAIN passed for the
  upgrade backfill, expired-run scheduler lookup, atomic claim/reclaim, and
  fenced heartbeat. The scheduler uses the partial expired-lease index; both
  ownership writes use UUID primary-key point lookups.
- 2026-10-19 — Implemented the three parallel evidence nodes with typed,
  independent state: order ownership/item lookup, semantic policy retrieval
  with authoritative citation verification, and transparent fraud-signal
  assessment. Added node-level retry policy, CockroachDB query-plan validation,
  AWS wrappers, and a checkpoint-backed smoke test. All three EXPLAINs passed.
  The smoke deliberately failed fraud once and proved that only fraud retried
  (order 1, policy 1, fraud 2); the completed state retained all results across
  four checkpoints and Prometheus captured successes plus the failure.
- 2026-10-19 — Added `3.12.107.117/32` to the Cockroach Cloud SQL allowlist and
  reran the fully instrumented classifier successfully (3/3). CockroachDB
  checkpoints were verified and cleaned up. Direct backend API validation
  found all 3 generated traces in Tempo, 12 structured node events in Loki,
  and the provisioned Grafana dashboard. End-to-end trace/log observability is
  operational.
- 2026-10-19 — Added a temporary port-8000 metrics endpoint to the classifier
  smoke run and replaced a fixed scrape delay with a bounded Prometheus
  confirmation handshake. Updated the dashboard to use retained
  `max_over_time` samples appropriate for short-lived batch runs. Final backend
  verification found 9 Tempo traces, 18 Loki events, a Prometheus classifier
  success counter of 3, and the provisioned Grafana dashboard with the updated
  queries. All four observability views now contain demo data.
- 2026-10-19 — Started the isolated Product Returns observability stack after
  verifying its secret and port prerequisites. Grafana, Prometheus, Tempo,
  Loki, and Alloy all passed readiness checks with zero container restarts;
  Grafana is published on port 3001. Enabled OTLP export. The subsequent graph
  smoke test stopped before node execution because Cockroach Cloud refused SQL
  connections from the resized host, indicating that `3.12.107.117/32` still
  needs SQL allowlist authorization. No workflow side effect occurred.
- 2026-10-19 — Completed a reconnect-safety documentation audit after the host
  resize. Updated `README.md`, this handoff, and `project.txt` with the new IP,
  completed capacity upgrade, confirmed desktop access to Grafana port 3001,
  current migration/rebuild sequence, and exact observability prerequisite and
  startup commands. Historical entries retain the former IP and earlier state
  only as dated history. The sole current blocker is adding
  `GRAFANA_ADMIN_PASSWORD` to ignored `keys.sh`.
- 2026-10-19 — Reconnected to the resized EC2 host at `3.12.107.117` with the
  unchanged pinned SSH fingerprint. Verified 4 vCPU, 15 GiB RAM, 310 GiB free
  disk, Docker/Compose availability, and the restored IAM listeners on ports
  3000/9090. Updated current host references. Product Returns startup remains
  paused because `GRAFANA_ADMIN_PASSWORD` is not yet exported by `keys.sh`.
- 2026-10-19 — Added end-to-end node instrumentation with OpenTelemetry spans,
  Prometheus metrics, credential-redacted structured JSON events, full
  sanitized node input/output capture, and trace/span/run/thread correlation.
  Installed and pinned the Python observability packages; the instrumented 3/3
  classifier smoke test passed on AWS. Applied migration `005` and used
  EXPLAIN to verify four Grafana access paths as `product_returns_app`. Added an
  isolated, version-pinned Grafana, Prometheus, Tempo, Loki, and Alloy Compose
  stack, provisioned data sources and the Graph Operations dashboard, and
  validated its structure on AWS without starting containers. Inventory found
  an unrelated IAM stack on ports 3000/9090 and only about 2 GiB host RAM, so
  Product Returns uses ports 3001/9091 and awaits a host resize before startup.
- 2026-10-19 — Added typed durable graph state, a structured-output
  request-classification node, the initial `START -> classify_request -> END`
  graph, and an AWS-only checkpoint-backed smoke test. Configured OpenAI
  `gpt-6-luna` with reasoning effort `none`. The test classified refund,
  complaint, and ambiguous messages correctly (3/3), verified persisted state
  through `product_returns_app`, and deleted all temporary checkpoint threads.
- 2026-10-17 — Installed and pinned `langchain-openai` 1.7.2 on AWS; resolver
  checks, imports, and `pip check` passed. Applied migration `004` as
  `product_returns_app`, producing the expected 35 fixture rows. Implemented
  deterministic return-policy parsing and ingestion, stored 8 verified OpenAI
  `text-embedding-3-small` vectors in namespace `standard-returns:1.0`, and
  passed a 3/3 semantic retrieval-and-citation smoke test. EXPLAIN verified the
  policy, clause, and namespace access paths; no approximate vector index is
  warranted for the eight-row corpus.
- 2026-10-17 — Added connector-compatible `policy_chunks` to migration `002`
  and reran it successfully as `ron`. CockroachDB created `VECTOR(1536)` with
  primary-region table locality and a namespace index. Migration `001` was
  rerun; `product_returns_app` has all four CRUD privileges. The database now
  has 19 tables and 76 table-grant rows. The cosine-query EXPLAIN succeeded.
- 2026-10-17 — Confirmed that policy citations require document title,
  version, section heading, and clause identifier, but not page number. The
  planned `policy_chunks` vector table has not yet been created.
- 2026-10-17 — Verified through a fresh pinned-host-key Plink session that
  sourcing `keys.sh`, `api-key.sh`, and `config.sh` makes `OPENAI_API_KEY`
  available to child processes. The diagnostic disclosed no secret value.
- 2026-10-17 — Recorded Linux-only `api-key.sh` as the source of
  `OPENAI_API_KEY`, added it to `.gitignore`, and updated host startup wrappers
  and documentation to source `keys.sh`, `api-key.sh`, then `config.sh` without
  exposing secret values.
- 2026-10-16 — Selected OpenAI `text-embedding-3-small` with its default 1,536
  dimensions for return-policy retrieval. Planned CockroachDB storage is
  `VECTOR(1536)` in a separate derived policy-chunk table. No vector table,
  embeddings, OpenAI dependency, or API key configuration has been created yet.
- 2026-10-16 — Validated all seed query plans and completed a transactional
  rollback test on AWS as `product_returns_app`. All 35 fixture rows passed
  their constraints, the transaction rolled back, and verification confirmed
  that no seed rows persisted.
- 2026-10-16 — Drafted rerunnable demo seed migration `004`, seven customer
  request scenarios, and a no-write EXPLAIN wrapper. Fixtures cover eligible,
  approval, policy-exclusion, expired-window, complaint, lookup-failure, and
  fraud-history paths. Nothing has been applied yet.
- 2026-10-16 — Added `scripts/run_checkpoint_smoke_test.sh` and ran it through
  Plink. The application identity successfully wrote, read, and listed three
  LangGraph checkpoints, then deleted the temporary thread. No owner credential
  or `setup()` call was used by the test.
- 2026-10-16 — Added `scripts/smoke_test_checkpoint.py`, a no-LLM runtime test
  that refuses owner credentials and exercises checkpoint write, read, list,
  and successful-thread cleanup through `product_returns_app`. It has not yet
  been executed.
- 2026-10-16 — Successfully ran LangGraph checkpoint setup as `ron`, creating
  `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, and
  `checkpoint_migrations`. Reran migration `001` and verified CRUD grants for
  `product_returns_app` on all 18 tables (72 table-grant rows).
- 2026-10-16 — Added `scripts/setup_langgraph_checkpoint.py`, a credential-safe
  deployment command that validates the `ron`/`product_returns` target and then
  invokes `CockroachDBSaver.setup()`. Updated the rebuild runbook with the exact
  command. The script has not yet been executed.
- 2026-10-16 — Expanded `README.md` into a start-over runbook: repository sync,
  host-only virtual-environment creation, secret/config loading, dependency
  installation and import validation, application-user prerequisite, database
  creation through a new `CRDB_RON_ADMIN_URL`, migrations in correct order, and
  final grant verification. Destructive reset commands remain excluded.
- 2026-10-16 — Installed the pinned core dependencies in the AWS-host Python
  3.11 virtual environment. Imports of LangChain, LangGraph,
  `langchain_cockroachdb`, and Psycopg all succeeded.
- 2026-10-16 — Successfully resolver-tested `requirements.txt` with pip
  `--dry-run` on the AWS host. No conflicts were reported and no packages were
  installed. The environment still uses pip 22.3.1 and should be upgraded
  before installation.
- 2026-10-16 — Added `requirements.txt` with reviewed direct pins for LangChain
  1.4.1, LangGraph 1.2.12, `langchain-cockroachdb` 0.4.0, Psycopg 3.3.6 binary,
  and `psycopg-pool` 3.3.3. Nothing has been installed yet; the LLM/embedding
  provider remains unselected.
- 2026-10-16 — Recreated `product_returns` after an intentional cascade drop
  and successfully applied migrations `001`, `002`, and `003`. Verified 14
  application tables, 56 CRUD grants for `product_returns_app`, database
  `CONNECT`, schema `USAGE`, and schema-scoped default table privileges.
- 2026-10-16 — Completed the first design review of migrations `002` and `003`.
  Confirmed that LangGraph owns full resumable checkpoint state while the
  application-owned workflow tables provide operational status, independent
  attempt history, approval records, refund idempotency, and a readable audit
  trail. Both migrations remain unexecuted.
- 2026-10-16 — Removed `fraud_signals` from the business-schema draft. Fraud is
  now explicitly modeled as a checkpointed node result with audit summaries.
  Added the versioned customer-facing return-policy document with stable clause
  IDs and documented the future chunk/embed/retrieve/verify pipeline. Added
  product-category snapshots and item activation time so exception checks do
  not depend on model inference from product names.
- 2026-10-16 — Added an explicit reconnect handoff snapshot at the top of this
  file with completed work, unexecuted drafts, environment rules, secrets
  handling, LangGraph setup ownership, and the next safe action.
- 2026-10-16 — Added `README.md` as the AWS-host runbook for environment
  activation, configuration, dependencies, the three SQL migrations, LangGraph
  checkpoint schema setup, grants, and the current safe execution order.
- 2026-10-16 — Drafted the commerce/returns schema and the durable workflow,
  approval, idempotent-refund, and audit schema. LangGraph saver checkpoints
  remain package-owned and are intentionally not reproduced in our migrations.
- 2026-10-16 — Executed and verified the runtime DCL migration. Corrected its
  default-privilege verification to include `IN SCHEMA public`; schema-scoped
  defaults are not displayed by the database-level form of the command.
- 2026-10-16 — Added `migrations/001_runtime_privileges.sql` as the reviewed,
  version-controlled DCL policy for database connection, public-schema usage,
  public-schema hardening, and CRUD access on current and future tables created
  by `ron`. The migration has not yet been executed.
- 2026-10-16 — `product_returns` database and `product_returns_app` user were
  created manually. Recorded the three-region topology, `aws-us-east-2` primary
  region, zone survival goal, and primary-region table-locality recommendation.
- 2026-10-16 — Recorded the new `config.sh` convention. `keys.sh` temporarily
  retains `CRDB_URL` and `CRDB_DATABASE`; these will be reorganized after the
  `product_returns` database and least-privilege application user are created.
- 2026-10-16 — Confirmed the exposed `ron` password was rotated. The owner
  credential is held in `CRDB_RON_PASSWORD`; no secret value was stored here.
- 2026-10-16 — Recorded sanitized CockroachDB endpoint and version information.
  Server 26.2.7 meets the integration's 25.4 minimum. Flagged the password
  exposed in chat for immediate rotation; it was not copied into this file.
- 2026-10-16 — Clarified that WinSCP Keep Remote Directory Up to Date is
  strictly local-to-remote; nothing is copied back to Windows. Recorded the
  successfully created host-only Python 3.11 virtual environment. Dependency
  installation remains paused.
- 2026-10-16 — Confirmed WinSCP synchronization target as
  `/home/ec2-user/langchain/product-returns`; WinSCP is running.
- 2026-10-16 — Confirmed Python 3.11.16 and CockroachDB CLI 26.1.0 are installed.
  Inspected `/home/ec2-user/langchain`; it currently contains two pre-existing
  files and no synchronized `product-returns` directory.
- 2026-10-16 — Independently verified the SSH host key and completed a
  successful read-only Plink inventory. Recorded Amazon Linux/EC2, storage,
  Python/pip mismatch, Git, CockroachDB CLI, and missing repository-path results.
- 2026-10-16 — Plink reached `16.59.136.190:22` and reported the ED25519 host
  key fingerprint recorded above. The connection stopped before authentication
  because the fingerprint has not been verified or cached.
- 2026-10-16 — Confirmed Python as the application language and `ec2-user` as
  the AWS SSH username.
- 2026-10-16 — Captured the AWS-only execution model, WinSCP synchronization,
  PuTTY-only SSH rule, host reference, initial graph design, durable pause/resume
  semantics, per-node retry requirement, policy verification, refund
  idempotency, audit requirements, provisional schema, and phased work plan.
