# ReturnFlow presentation

This Next.js application is the customer-facing concept experience for the
Product Returns Graph demo. Its visual language follows the successful NextEra
Equipment Intelligence demonstration while telling a distinct retail-return
story.

The current vertical slice includes:

- a natural-language customer return request;
- a clearly marked presenter control that loads all seven current demo orders
  from CockroachDB, regardless of customer, without advertising the outcome;
- AI extraction of a customer's explicit device-activation claim, visibly
  grounded in a verbatim quote before deterministic comparison with the order
  record;
- AI extraction of explicit product-safety concerns, visibly grounded in the
  customer's exact words and acknowledged without changing deterministic
  eligibility;
- an animated graph journey showing classification, the parallel evidence
  round, decision, quantity reservation, human approval, and refund;
- selectable nodes with their input, output, checkpoint, trace, and audit
  context;
- a verified policy quotation with version, heading, and clause identifier;
- a manager-approval interaction that explains durable pause and resume; and
- a presenter-only resilience control that can stop one evidence node once,
  display the released lease and published checkpoint, copy exact run-scoped
  database inspection SQL, and resume with a new worker generation; and
- a separate payment-provider-success failure that stops before local refund
  completion, then proves one provider refund from two keyed requests; and
- responsive layouts for presentation displays and narrower browsers.

## Live integration boundary

The visual flow calls the real Python/LangGraph runtime. The browser submits a
return, polls its CockroachDB-backed snapshot, displays durable `node_attempts`,
and records manager approval or rejection through same-origin Next.js API
routes. Those server routes proxy to `http://127.0.0.1:8010`; the Python API is
not exposed publicly. Refunds use the isolated deterministic demo-provider
ledger, not a real payment network.

The **Start another demo** action removes only runs whose thread ID has the
reserved `returnflow-` prefix, deletes their LangGraph checkpoints, and restores
their synthetic item capacity. It refuses to reset a currently running run.

For the resilience story, select a node under **Resilience test** before
submitting. At the safe stop, the two successful evidence siblings remain
green, the injected node is red, and the page shows that the lease is released.
Use **Copy database inspection SQL** for nine UUID-scoped CockroachDB queries,
then select **Resume with a new worker**. Only the failed node should gain a
second attempt; the new lease generation completes the remaining graph.

For payment resilience, select eligible `DEMO-1001` and **Fail after
payment-provider success**. The stopped run shows the provider refund ID and
stable idempotency key. Resume manually; the provider returns the same refund
on request two. The proof panel shows one refund issued, two provider requests,
zero duplicate payments, local attempts, audit events, and Grafana links.
The AWS proxy proof is `bash scripts/run_payment_resilience_api_smoke_test.sh`.

`DEMO-1007` is the focused risk demonstration: Bob's recent `$140.39`
coffee-maker order is otherwise returnable, but his restricted account and
three prior refunds produce a risk score of 90 and require manager review solely
for `FRAUD_REVIEW_REQUIRED`.

`DEMO-1004` is the human-AI collaboration demonstration. OpenAI extracts the
customer's exact “has not been activated” assertion, application code verifies
that quote against the original message, and deterministic rules find that it
conflicts with CockroachDB's activation timestamp. The result is
`ACTIVATION_STATUS_CONFLICT`, not an automatic override or denial, and the
existing durable manager checkpoint resolves it.

`DEMO-1001` demonstrates useful AI without uncontrolled authority. The default
request says the toaster gets very hot and may scorch a countertop. OpenAI
extracts and the application verifies that safety concern, the evidence panel
shows the exact quote, and the final refund message confirms that it was
recorded for product-safety follow-up. The insight does not itself approve,
deny, or reroute the return, and the demo does not claim an external party was
contacted.

## Run on the AWS host

Nothing in this directory should be executed on Windows. After WinSCP has
mirrored the files, use PuTTY to run:

```bash
cd /home/ec2-user/langchain/product-returns/presentation
npm install
npm run typecheck
npm run build
npm start
```

For a persistent background process, use the repository wrappers instead:

```bash
bash /home/ec2-user/langchain/product-returns/scripts/build_presentation.sh
bash /home/ec2-user/langchain/product-returns/scripts/start_returnflow_api.sh
bash /home/ec2-user/langchain/product-returns/scripts/start_presentation.sh
bash /home/ec2-user/langchain/product-returns/scripts/stop_presentation.sh
bash /home/ec2-user/langchain/product-returns/scripts/stop_returnflow_api.sh
```

Each start wrapper records the exact process ID and waits for a successful local
HTTP health check. Each stop wrapper signals only its recorded process. API logs
are under `/home/ec2-user/.local/state/product-returns/api/`; presentation logs
are under `/home/ec2-user/.local/state/product-returns/presentation/`.

The application listens on `0.0.0.0:3002`. Ports `3000` and `3001` are already
used by Grafana services on the AWS host. The EC2 security group must explicitly
allow the presenter's source IP to reach TCP port `3002` before the browser can
open `http://3.12.107.117:3002`.

The dependency versions are pinned in `package.json`. Next.js `16.4.2` was
selected after `16.3.2` produced a critical security advisory. On 2026-10-20,
`npm audit`, strict TypeScript checking, and the production build all completed
successfully on the AWS host.
