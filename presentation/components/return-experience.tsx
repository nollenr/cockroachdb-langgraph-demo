"use client";

import { useEffect, useMemo, useState } from "react";

import {
  ArrowIcon,
  CheckIcon,
  DatabaseIcon,
  OrderIcon,
  PulseIcon,
  ReturnIcon,
  ShieldIcon,
} from "./icons";

type Outcome = "automatic" | "approval" | "denied";
type FailureNode = "" | "lookup_order" | "retrieve_policy" | "assess_fraud" | "issue_refund";
type Phase =
  | "ready"
  | "classifying"
  | "evidence"
  | "deciding"
  | "reserving"
  | "waiting"
  | "recovery"
  | "refunding"
  | "completed"
  | "redirected"
  | "denied";
type NodeStatus = "idle" | "active" | "complete" | "waiting" | "failed" | "blocked";

interface Scenario {
  accountSignal: string;
  customer: string;
  description: string;
  externalCustomerId: string;
  message: string;
  orderAge: string;
  orderNumber: string;
  outcome: Outcome;
  policyClause: string;
  policyHeading: string;
  product: string;
  refund: string;
  sku: string;
}

interface DemoOrder {
  currency: string;
  customer_name: string;
  external_customer_id: string;
  items: Array<{
    line_total: number;
    product_name: string;
    quantity: number;
    sku: string;
  }>;
  order_number: string;
  ordered_at: string;
  total_amount: number;
}

interface GraphNode {
  detail: string;
  id: string;
  label: string;
  output: (scenario: Scenario) => string;
}

interface NodeAttempt {
  attempt_number: number;
  attempt_status: "started" | "succeeded" | "retryable_failure" | "failed";
  duration_ms: number | null;
  error_message: string | null;
  input_state: Record<string, unknown> | null;
  node_name: string;
  output_summary: Record<string, unknown> | null;
}

interface RunSnapshot {
  approval: { approval_status: string; approval_reason: string; decision_note: string | null; refund_amount: string } | null;
  audit_events: Array<{ event_data?: Record<string, unknown>; event_type: string; sequence_number: number }>;
  classified_intent: "unclassified" | "refund" | "complaint" | "other";
  graph_version: string;
  failure_injection: {
    node_name: Exclude<FailureNode, "">;
    failure_mode: string;
    injection_status: "planned" | "triggered" | "resumed";
    triggered_at: string | null;
    resumed_at: string | null;
  } | null;
  lease_owner: string | null;
  lease_generation: number;
  latest_checkpoint_id: string | null;
  node_attempts: NodeAttempt[];
  order_number: string;
  refund: { refund_amount: string; refund_status: string; provider_refund_id: string | null; idempotency_key: string } | null;
  refund_attempts: Array<{ attempt_number: number; attempt_status: string; provider_request_id: string; error_code: string | null }>;
  provider_refund: { provider_refund_id: string; idempotency_key: string; request_count: number; provider_refund_count: number; provider_status: string } | null;
  request_text: string;
  request_status: string;
  run_id: string;
  run_status: string;
  state_version: number;
  trace_id: string;
}

const scenarios: Scenario[] = [
  {
    accountSignal: "Account active · no elevated signals",
    customer: "Ron",
    description: "Eligible return · automatic refund",
    externalCustomerId: "CUST-RON",
    message: "I want to return the toaster from order DEMO-1001. I've used it quite a bit but it gets really hot and I'm worried it will scorch my countertops.",
    orderAge: "Purchased 10 days ago",
    orderNumber: "DEMO-1001",
    outcome: "automatic",
    policyClause: "Most products may be returned within 30 calendar days after the original purchase date.",
    policyHeading: "Return eligibility · RET-ELIGIBILITY-001",
    product: "Two-Slice Toaster",
    refund: "$53.99",
    sku: "TOAST-2SL",
  },
  {
    accountSignal: "Account active · no elevated signals",
    customer: "Sally",
    description: "High-value return · manager approval",
    externalCustomerId: "CUST-SALLY",
    message: "Please return the Pro 900 vacuum from order DEMO-1002. It is still in good condition.",
    orderAge: "Purchased 8 days ago",
    orderNumber: "DEMO-1002",
    outcome: "approval",
    policyClause: "A refund greater than $500.00 requires manager approval before it can be issued.",
    policyHeading: "Manual review · RET-APPROVAL-001",
    product: "Pro 900 Vacuum",
    refund: "$700.92",
    sku: "VAC-PRO-900",
  },
  {
    accountSignal: "Restricted account · 3 prior returns",
    customer: "Bob",
    description: "Policy exception · explainable denial",
    externalCustomerId: "CUST-BOB",
    message: "I want a refund for the gift card on order DEMO-1003.",
    orderAge: "Purchased 5 days ago",
    orderNumber: "DEMO-1003",
    outcome: "denied",
    policyClause: "Gift cards are final sale and cannot be returned, exchanged, or redeemed for cash except where required by law.",
    policyHeading: "Non-returnable products · RET-EXCEPTION-001",
    product: "$100 Gift Card",
    refund: "$100.00",
    sku: "GIFT-100",
  },
  {
    accountSignal: "Account active · no elevated signals",
    customer: "Ron",
    description: "AI-detected activation conflict · manager review",
    externalCustomerId: "CUST-RON",
    message: "I want to return the iPhone from order DEMO-1004. The phone has not been activated and I would like to return it.",
    orderAge: "Purchased 7 days ago",
    orderNumber: "DEMO-1004",
    outcome: "approval",
    policyClause: "Activated mobile phones, including activated iPhones, cannot be returned under the standard return policy.",
    policyHeading: "Non-returnable products · RET-EXCEPTION-001",
    product: "iPhone 17 256GB",
    refund: "$1,078.92",
    sku: "IPHONE-17-256",
  },
  {
    accountSignal: "Account active · no elevated signals",
    customer: "Sally",
    description: "Outside the return window",
    externalCustomerId: "CUST-SALLY",
    message: "I want to return the coffee maker from order DEMO-1005.",
    orderAge: "Purchased 45 days ago",
    orderNumber: "DEMO-1005",
    outcome: "denied",
    policyClause: "Most products may be returned within 30 calendar days after the original purchase date.",
    policyHeading: "Return eligibility · RET-ELIGIBILITY-001",
    product: "12-Cup Coffee Maker",
    refund: "$140.39",
    sku: "COFFEE-12C",
  },
  {
    accountSignal: "Restricted account · 3 prior refunds",
    customer: "Bob",
    description: "Expired return with elevated risk",
    externalCustomerId: "CUST-BOB",
    message: "I want to return the toasters from order DEMO-1006.",
    orderAge: "Purchased 60 days ago",
    orderNumber: "DEMO-1006",
    outcome: "denied",
    policyClause: "Most products may be returned within 30 calendar days after the original purchase date.",
    policyHeading: "Return eligibility · RET-ELIGIBILITY-001",
    product: "Three Two-Slice Toasters",
    refund: "$161.97",
    sku: "TOAST-2SL",
  },
  {
    accountSignal: "Restricted account · 3 prior refunds · risk review",
    customer: "Bob",
    description: "Fraud signals require manager review",
    externalCustomerId: "CUST-BOB",
    message: "I want to return the coffee maker from order DEMO-1007. It is unused and in the original packaging.",
    orderAge: "Purchased 6 days ago",
    orderNumber: "DEMO-1007",
    outcome: "approval",
    policyClause: "Returns may be sent for manual review when required to confirm account activity.",
    policyHeading: "Review and approval · RET-APPROVAL-001",
    product: "12-Cup Coffee Maker",
    refund: "$140.39",
    sku: "COFFEE-12C",
  },
];

const graphNodes: GraphNode[] = [
  {
    id: "classify",
    label: "Understand request",
    detail: "OpenAI classification",
    output: () => "Intent: refund request · confidence: high",
  },
  {
    id: "order",
    label: "Verify purchase",
    detail: "CockroachDB order record",
    output: (scenario) => `${scenario.orderNumber} · ${scenario.product} · delivered`,
  },
  {
    id: "policy",
    label: "Find policy",
    detail: "Verified vector retrieval",
    output: (scenario) => scenario.policyHeading,
  },
  {
    id: "fraud",
    label: "Assess account",
    detail: "Deterministic risk evidence",
    output: (scenario) => scenario.accountSignal,
  },
  {
    id: "decision",
    label: "Decide return",
    detail: "Explainable business rules",
    output: (scenario) => scenario.outcome === "denied"
      ? "Not eligible · non-returnable product"
      : scenario.outcome === "approval"
        ? "Eligible · manager approval required"
        : "Eligible · automatic refund",
  },
  {
    id: "reserve",
    label: "Reserve quantity",
    detail: "Concurrency-safe inventory",
    output: () => "1 unit reserved · duplicate protection active",
  },
  {
    id: "approval",
    label: "Manager approval",
    detail: "Durable human checkpoint",
    output: () => "Waiting safely in CockroachDB · no process held open",
  },
  {
    id: "refund",
    label: "Issue refund",
    detail: "Idempotent payment request",
    output: (scenario) => `${scenario.refund} · original payment method · one provider refund`,
  },
];

const nodeNames: Record<string, string> = {
  classify: "classify_request",
  order: "lookup_order",
  policy: "retrieve_policy",
  fraud: "assess_fraud",
  decision: "decide_return",
  reserve: "reserve_return_items",
  refund: "issue_refund",
};

function latestAttempt(nodeId: string, snapshot: RunSnapshot | null): NodeAttempt | null {
  if (!snapshot || nodeId === "approval") return null;
  return [...snapshot.node_attempts]
    .reverse()
    .find((attempt) => attempt.node_name === nodeNames[nodeId]) ?? null;
}

function statusForNode(nodeId: string, phase: Phase, snapshot: RunSnapshot | null): NodeStatus {
  if (phase === "ready") return "idle";
  if (nodeId === "approval") {
    if (snapshot?.run_status === "waiting_for_approval") return "waiting";
    if (snapshot?.approval?.approval_status === "approved" || snapshot?.approval?.approval_status === "rejected") return "complete";
    if (snapshot && ["completed", "rejected"].includes(snapshot.run_status)) return "blocked";
    return "idle";
  }
  const attempt = latestAttempt(nodeId, snapshot);
  if (attempt?.attempt_status === "succeeded") return "complete";
  if (attempt?.attempt_status === "started") return "active";
  if (attempt?.attempt_status === "retryable_failure" && phase === "recovery") return "failed";
  if (attempt && ["failed", "retryable_failure"].includes(attempt.attempt_status)) {
    return snapshot && ["completed", "rejected", "failed"].includes(snapshot.run_status) ? "blocked" : "active";
  }
  if (snapshot && ["completed", "rejected", "failed"].includes(snapshot.run_status)) return "blocked";
  return "idle";
}

function phaseForSnapshot(snapshot: RunSnapshot): Phase {
  if (snapshot.run_status === "completed") return "completed";
  if (snapshot.run_status === "rejected" && ["complaint", "other"].includes(snapshot.classified_intent)) return "redirected";
  if (snapshot.run_status === "rejected" || snapshot.run_status === "failed") return "denied";
  if (snapshot.run_status === "waiting_for_approval") return "waiting";
  if (
    snapshot.run_status === "retry_wait"
    && snapshot.failure_injection?.injection_status === "triggered"
  ) return "recovery";
  const names = new Set(snapshot.node_attempts.map((attempt) => attempt.node_name));
  if (names.has("issue_refund")) return "refunding";
  if (names.has("reserve_return_items")) return "reserving";
  if (names.has("decide_return")) return "deciding";
  if (names.has("lookup_order") || names.has("retrieve_policy") || names.has("assess_fraud")) return "evidence";
  return "classifying";
}

function selectedNodeForPhase(phase: Phase): string {
  const selectedByPhase: Partial<Record<Phase, string>> = {
    evidence: "policy",
    deciding: "decision",
    reserving: "reserve",
    waiting: "approval",
    recovery: "fraud",
    refunding: "refund",
    completed: "refund",
    redirected: "classify",
    denied: "decision",
  };
  return selectedByPhase[phase] ?? "classify";
}

function terminalCopy(snapshot: RunSnapshot | null, scenario: Scenario): {
  eyebrow: string;
  heading: string;
  detail: string;
} {
  if (snapshot?.run_status === "completed") {
    const decisionOutput = latestAttempt("decision", snapshot)?.output_summary?.decision as {
      customer_acknowledgement?: string | null;
    } | undefined;
    return {
      eyebrow: "Refund complete",
      heading: `${scenario.refund} refunded to the original payment method`,
      detail: decisionOutput?.customer_acknowledgement
        ? `${decisionOutput.customer_acknowledgement} Your refund was issued exactly once.`
        : "The payment provider accepted one idempotent refund. You’ll also receive an email confirmation.",
    };
  }
  if (snapshot?.classified_intent === "complaint") {
    return {
      eyebrow: "Request understood",
      heading: "This looks like a product question—not a return request",
      detail: "No return or refund was started. For a safety or product-use concern, please contact customer support for the appropriate guidance.",
    };
  }
  if (snapshot?.classified_intent === "other") {
    return {
      eyebrow: "Request understood",
      heading: "No return request was detected",
      detail: "The refund workflow stopped after classification, so no order, policy, account, or payment action was taken.",
    };
  }
  if (snapshot?.approval?.approval_status === "rejected") {
    return {
      eyebrow: "Decision complete",
      heading: "The manager did not approve this return",
      detail: snapshot.approval.decision_note ?? snapshot.approval.approval_reason,
    };
  }
  const decisionOutput = latestAttempt("decision", snapshot)?.output_summary?.decision as {
    explanation?: string;
    reason_codes?: string[];
  } | undefined;
  if (decisionOutput?.reason_codes?.includes("GIFT_CARD_FINAL_SALE")) {
    return {
      eyebrow: "Decision complete",
      heading: "Gift cards are final sale",
      detail: decisionOutput.explanation ?? "The current return policy identifies gift cards as non-returnable.",
    };
  }
  return {
    eyebrow: snapshot?.run_status === "failed" ? "Workflow stopped" : "Decision complete",
    heading: snapshot?.run_status === "failed" ? "We couldn’t complete this request" : "This return isn’t eligible",
    detail: decisionOutput?.explanation ?? "The recorded workflow outcome explains why no refund was issued.",
  };
}

function safetyInsight(snapshot: RunSnapshot | null): {
  category?: string;
  supporting_text?: string;
} | null {
  const classification = latestAttempt("classify", snapshot)?.output_summary?.classification as {
    product_safety_concern?: {
      category?: string;
      status?: string;
      supporting_text?: string;
      verified_in_message?: boolean;
    };
  } | undefined;
  const concern = classification?.product_safety_concern;
  return concern?.status === "present" && concern.verified_in_message
    ? concern
    : null;
}

function relevantPolicyCitation(
  scenario: Scenario,
  snapshot: RunSnapshot | null,
): { clause_key?: string; quote?: string; section_heading?: string } | null {
  const output = latestAttempt("policy", snapshot)?.output_summary;
  const policy = output?.policy_evidence as {
    citations?: Array<{ clause_key?: string; quote?: string; section_heading?: string }>;
  } | undefined;
  const citations = policy?.citations ?? [];
  const expectedClause = scenario.policyHeading.split("·").at(-1)?.trim();
  return citations.find((citation) => citation.clause_key === expectedClause) ?? citations[0] ?? null;
}

function actualNodeOutput(node: GraphNode, scenario: Scenario, snapshot: RunSnapshot | null): string {
  const attempt = latestAttempt(node.id, snapshot);
  if (attempt?.attempt_status === "retryable_failure") {
    return attempt.error_message ?? "Injected one-shot failure · retry required";
  }
  const output = attempt?.output_summary;
  if (!output) return node.output(scenario);
  const classification = output.classification as {
    confidence?: number;
    device_activation_claim?: {
      status?: string;
      supporting_text?: string;
      verified_in_message?: boolean;
    };
    product_safety_concern?: {
      category?: string;
      status?: string;
      supporting_text?: string;
      verified_in_message?: boolean;
    };
    intent?: string;
  } | undefined;
  if (classification) {
    const claim = classification.device_activation_claim;
    const claimSummary = claim?.verified_in_message && claim.status === "not_activated"
      ? ` · AI extracted: not activated (“${claim.supporting_text}”)`
      : "";
    const concern = classification.product_safety_concern;
    const safetySummary = concern?.verified_in_message && concern.status === "present"
      ? ` · AI insight: ${concern.category}`
      : "";
    return `Intent: ${classification.intent} · confidence: ${Math.round((classification.confidence ?? 0) * 100)}%${claimSummary}${safetySummary}`;
  }
  const order = output.order_lookup as { found?: boolean; items?: Array<{ product_name?: string }>; order_status?: string } | undefined;
  if (order) return order.found ? `${scenario.orderNumber} · ${order.items?.[0]?.product_name ?? scenario.product} · ${order.order_status}` : "Order not found";
  const policy = output.policy_evidence as { citations?: Array<{ clause_key?: string; section_heading?: string }> } | undefined;
  if (policy) {
    const citation = relevantPolicyCitation(scenario, snapshot);
    return `${citation?.section_heading ?? "Policy section"} · ${citation?.clause_key ?? "verified"}`;
  }
  const fraud = output.fraud_assessment as { risk_level?: string; risk_score?: number } | undefined;
  if (fraud) return `${fraud.risk_level ?? "unknown"} risk · score ${fraud.risk_score ?? 0}`;
  const decision = output.decision as { explanation?: string } | undefined;
  if (decision) return decision.explanation ?? node.output(scenario);
  const reservation = output.return_reservation as { explanation?: string } | undefined;
  if (reservation) return reservation.explanation ?? node.output(scenario);
  const refund = output.refund_result as { currency?: string; refund_amount?: string } | undefined;
  if (refund) return `${refund.currency ?? "USD"} ${refund.refund_amount ?? ""} · provider accepted one refund`;
  return node.output(scenario);
}

function statusLabel(status: NodeStatus): string {
  if (status === "complete") return "Complete";
  if (status === "active") return "Running";
  if (status === "waiting") return "Waiting";
  if (status === "failed") return "Retry needed";
  if (status === "blocked") return "Not needed";
  return "Queued";
}

function demoOrderLabel(order: DemoOrder): string {
  const itemSummary = order.items
    .map((item) => `${item.quantity > 1 ? `${item.quantity}× ` : ""}${item.product_name}`)
    .join(", ");
  const amount = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: order.currency,
  }).format(Number(order.total_amount));
  return `${order.order_number} · ${order.customer_name} · ${itemSummary} · ${amount}`;
}

function NodeCard({
  node,
  scenario,
  output,
  selected,
  status,
  onSelect,
}: {
  node: GraphNode;
  scenario: Scenario;
  output?: string;
  selected: boolean;
  status: NodeStatus;
  onSelect: () => void;
}) {
  return (
    <button
      className={`graph-node node-${status}${selected ? " selected" : ""}`}
      onClick={onSelect}
      type="button"
    >
      <span className="node-state" aria-hidden="true">
        {status === "complete" ? <CheckIcon /> : status === "active" ? <span className="node-spinner" /> : status === "waiting" ? "II" : status === "failed" ? "!" : ""}
      </span>
      <span className="node-copy">
        <strong>{node.label}</strong>
        <small>{node.detail}</small>
      </span>
      <span className={`node-status status-${status}`}>{statusLabel(status)}</span>
      {status === "complete" ? <span className="node-mini-output">{output ?? node.output(scenario)}</span> : null}
    </button>
  );
}

export function ReturnExperience() {
  const [demoOrders, setDemoOrders] = useState<DemoOrder[]>([]);
  const [selectedOrderNumber, setSelectedOrderNumber] = useState(scenarios[0].orderNumber);
  const [message, setMessage] = useState(scenarios[0].message);
  const [failureNode, setFailureNode] = useState<FailureNode>("");
  const [inspectionCopied, setInspectionCopied] = useState(false);
  const [phase, setPhase] = useState<Phase>("ready");
  const [selectedNodeId, setSelectedNodeId] = useState("classify");
  const [view, setView] = useState<"request" | "journey">("request");
  const [runId, setRunId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const scenario = scenarios.find((candidate) => candidate.orderNumber === selectedOrderNumber) ?? scenarios[0];
  const scenarioIndex = Math.max(0, scenarios.findIndex((candidate) => candidate.orderNumber === scenario.orderNumber));
  const selectedNode = graphNodes.find((node) => node.id === selectedNodeId) ?? graphNodes[0];
  const selectedAttempt = latestAttempt(selectedNodeId, snapshot);
  const policyCitation = relevantPolicyCitation(scenario, snapshot);
  const runStarted = runId !== null;
  const terminal = terminalCopy(snapshot, scenario);
  const detectedSafetyInsight = safetyInsight(snapshot);
  const recoveryNodeId = snapshot?.failure_injection?.node_name === "issue_refund"
    ? "refund"
    : snapshot?.failure_injection?.node_name === "lookup_order"
    ? "order"
    : snapshot?.failure_injection?.node_name === "retrieve_policy"
      ? "policy"
      : "fraud";
  const paymentStory = snapshot?.failure_injection?.node_name === "issue_refund";
  const providerRefund = snapshot?.provider_refund;
  const grafanaBase = "http://3.12.107.117:3001";
  const traceLink = snapshot?.trace_id
    ? `${grafanaBase}/explore?left=${encodeURIComponent(JSON.stringify({ datasource: "tempo", queries: [{ refId: "A", queryType: "traceId", query: snapshot.trace_id }], range: { from: "now-6h", to: "now" } }))}`
    : null;
  const logsLink = runId
    ? `${grafanaBase}/explore?left=${encodeURIComponent(JSON.stringify({ datasource: "loki", queries: [{ refId: "A", expr: `{job="product-returns"} | json | run_id="${runId}"`, queryType: "range" }], range: { from: "now-6h", to: "now" } }))}`
    : null;

  useEffect(() => {
    let cancelled = false;
    async function loadOrders() {
      try {
        const response = await fetch("/api/demo-orders", { cache: "no-store" });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? "Could not load demo orders");
        if (!cancelled) setDemoOrders(body.orders as DemoOrder[]);
      } catch (error) {
        if (!cancelled) setApiError(error instanceof Error ? error.message : "Could not load demo orders");
      }
    }
    void loadOrders();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const savedRunId = window.localStorage.getItem("returnflow:lastRunId");
    if (!savedRunId) return;
    let cancelled = false;
    async function restore() {
      try {
        const response = await fetch(`/api/returns/${savedRunId}`, { cache: "no-store" });
        if (response.status === 404) {
          window.localStorage.removeItem("returnflow:lastRunId");
          return;
        }
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? "Could not restore the previous workflow");
        if (cancelled) return;
        const restored = body as RunSnapshot;
        const nextPhase = phaseForSnapshot(restored);
        setSelectedOrderNumber(restored.order_number);
        setMessage(restored.request_text);
        setRunId(restored.run_id);
        setSnapshot(restored);
        setPhase(nextPhase);
        setSelectedNodeId(nextPhase === "recovery" ? (
          restored.failure_injection?.node_name === "issue_refund" ? "refund"
            : restored.failure_injection?.node_name === "lookup_order" ? "order"
            : restored.failure_injection?.node_name === "retrieve_policy" ? "policy" : "fraud"
        ) : selectedNodeForPhase(nextPhase));
        setView("journey");
      } catch (error) {
        if (!cancelled) setApiError(error instanceof Error ? error.message : "Could not restore the previous workflow");
      }
    }
    void restore();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    async function refresh() {
      try {
        const response = await fetch(`/api/returns/${runId}`, { cache: "no-store" });
        const body = await response.json();
        if (!response.ok) throw new Error(body.detail ?? "Could not load workflow status");
        if (cancelled) return;
        const nextSnapshot = body as RunSnapshot;
        setSnapshot(nextSnapshot);
        setPhase((previous) => {
          const next = phaseForSnapshot(nextSnapshot);
          if (next !== previous) {
            setSelectedNodeId(next === "recovery" ? (
              nextSnapshot.failure_injection?.node_name === "issue_refund" ? "refund"
                : nextSnapshot.failure_injection?.node_name === "lookup_order" ? "order"
                : nextSnapshot.failure_injection?.node_name === "retrieve_policy" ? "policy" : "fraud"
            ) : selectedNodeForPhase(next));
          }
          return next;
        });
        setApiError(null);
      } catch (error) {
        if (!cancelled) setApiError(error instanceof Error ? error.message : "Could not load workflow status");
      }
    }
    void refresh();
    const timer = window.setInterval(refresh, 650);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [runId, selectedNodeId]);

  const completedCount = useMemo(
    () => graphNodes.filter((node) => statusForNode(node.id, phase, snapshot) === "complete").length,
    [phase, snapshot],
  );

  function chooseScenario(orderNumber: string) {
    const next = scenarios.find((candidate) => candidate.orderNumber === orderNumber);
    if (!next) return;
    setSelectedOrderNumber(orderNumber);
    setMessage(next.message);
    setFailureNode("");
    setPhase("ready");
    setSelectedNodeId("classify");
    setView("request");
    setRunId(null);
    setSnapshot(null);
    setApiError(null);
  }

  async function beginReturn() {
    setSubmitting(true);
    setApiError(null);
    try {
      const priorRunId = window.localStorage.getItem("returnflow:lastRunId");
      if (priorRunId) {
        const reset = await fetch(`/api/returns/${priorRunId}`, { method: "DELETE" });
        if (!reset.ok && reset.status !== 404) {
          const resetBody = await reset.json();
          throw new Error(resetBody.detail ?? "Could not reset the previous synthetic demo run");
        }
        window.localStorage.removeItem("returnflow:lastRunId");
      }
      const response = await fetch("/api/returns", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          customer_external_id: scenario.externalCustomerId,
          order_number: scenario.orderNumber,
          request_text: message,
          failure_node: failureNode || null,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not create the return workflow");
      setRunId(body.run_id);
      window.localStorage.setItem("returnflow:lastRunId", body.run_id);
      setPhase("classifying");
      setSelectedNodeId("classify");
      setView("journey");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not create the return workflow");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitManagerDecision(decision: "approved" | "rejected") {
    if (!runId) return;
    setSubmitting(true);
    setApiError(null);
    try {
      const response = await fetch(`/api/returns/${runId}/manager-decision`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          decision,
          decided_by: "manager.demo",
          decision_note: `ReturnFlow presenter ${decision} this request.`,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not record the manager decision");
      setPhase(decision === "approved" ? "refunding" : "denied");
      setSelectedNodeId(decision === "approved" ? "refund" : "approval");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not record the manager decision");
    } finally {
      setSubmitting(false);
    }
  }

  async function resumeRecovery() {
    if (!runId) return;
    setSubmitting(true);
    setApiError(null);
    try {
      const response = await fetch(`/api/returns/${runId}/resume`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not resume the workflow");
      setPhase(paymentStory ? "refunding" : "evidence");
      setSelectedNodeId(recoveryNodeId);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not resume the workflow");
    } finally {
      setSubmitting(false);
    }
  }

  async function copyInspectionSql() {
    if (!runId) return;
    try {
      const response = await fetch(`/api/returns/${runId}/inspection-sql`, { cache: "no-store" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Could not create inspection SQL");
      if (window.isSecureContext && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(body.sql);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = body.sql;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("Browser copy was blocked; open the SQL endpoint directly");
      }
      setInspectionCopied(true);
      window.setTimeout(() => setInspectionCopied(false), 2500);
      setApiError(null);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not copy inspection SQL");
    }
  }

  async function resetDemo() {
    const priorRunId = runId ?? window.localStorage.getItem("returnflow:lastRunId");
    if (priorRunId) {
      try {
        const response = await fetch(`/api/returns/${priorRunId}`, { method: "DELETE" });
        if (!response.ok && response.status !== 404) {
          const body = await response.json();
          throw new Error(body.detail ?? "Could not reset the synthetic demo run");
        }
        window.localStorage.removeItem("returnflow:lastRunId");
      } catch (error) {
        setApiError(error instanceof Error ? error.message : "Could not reset the synthetic demo run");
        return;
      }
    }
    setPhase("ready");
    setSelectedNodeId("classify");
    setView("request");
    setFailureNode("");
    setRunId(null);
    setSnapshot(null);
    setApiError(null);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <button className="product-mark" onClick={resetDemo} type="button" aria-label="ReturnFlow home">
          <span className="mark-glyph"><ReturnIcon /></span>
          <span><strong>ReturnFlow</strong><small>Intelligent returns</small></span>
        </button>

        <nav className="primary-nav" aria-label="Primary navigation">
          <span className="nav-heading">Your account</span>
          <button className="nav-item active" onClick={() => setView("request")} type="button"><ReturnIcon />Start a return</button>
          <span className="nav-item"><OrderIcon />Orders<small>{demoOrders.length || 7}</small></span>
          <span className="nav-item"><PulseIcon />Return activity</span>
          <span className="nav-heading nav-heading-second">Demo workspace</span>
          <button className={view === "journey" ? "nav-item active" : "nav-item"} onClick={() => runStarted && setView("journey")} type="button"><ShieldIcon />Decision journey</button>
        </nav>

        <div className="platform-card">
          <span className="platform-icon"><DatabaseIcon /></span>
          <span><strong>Durable by design</strong><small>LangGraph + CockroachDB</small></span>
        </div>
        <div className="sidebar-status"><span className="connection-dot" /><span><strong>All systems healthy</strong><small>Workflow services connected</small></span></div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div className="environment-pill"><span />Concept demo</div>
          <div className="topbar-context">
            <span className="synthetic-label">Synthetic customer data</span>
            <span className="topbar-divider" />
            <span className="customer-avatar">{scenario.customer.slice(0, 1)}</span>
            <span className="customer-copy"><strong>{scenario.customer}</strong><small>Demo customer</small></span>
          </div>
        </header>

        <main className="main-content">
          <section className="scenario-bar" aria-label="Presenter order control">
            <span><i>Presenter controls</i><strong>Choose any order</strong></span>
            <div className="order-selector-wrap">
              <label htmlFor="demo-order">Synthetic order</label>
              <select
                disabled={runStarted || demoOrders.length === 0}
                id="demo-order"
                onChange={(event) => chooseScenario(event.target.value)}
                value={selectedOrderNumber}
              >
                {demoOrders.length === 0 ? <option value={selectedOrderNumber}>Loading current orders…</option> : null}
                {demoOrders.map((order) => <option key={order.order_number} value={order.order_number}>{demoOrderLabel(order)}</option>)}
              </select>
              <small>{demoOrders.length || 7} database-backed synthetic orders · outcome determined by the graph</small>
            </div>
            <div className="failure-selector-wrap">
              <label htmlFor="failure-node">Resilience test</label>
              <select
                disabled={runStarted}
                id="failure-node"
                onChange={(event) => setFailureNode(event.target.value as FailureNode)}
                value={failureNode}
              >
                <option value="">No injected failure</option>
                <option value="lookup_order">Fail purchase verification once</option>
                <option value="retrieve_policy">Fail policy retrieval once</option>
                <option value="assess_fraud">Fail account assessment once</option>
                <option value="issue_refund">Fail after payment-provider success</option>
              </select>
              <small>Presenter-only · one-shot · durably recoverable</small>
            </div>
          </section>

          {apiError ? <div className="api-error" role="alert"><strong>ReturnFlow needs attention</strong><span>{apiError}</span></div> : null}

          {view === "request" ? (
            <div className="page-stack request-page">
              <section className="page-heading-row">
                <div><span className="eyebrow">Returns / New request</span><h1>Let&apos;s make this right.</h1><p>Tell us what you&apos;d like to return. We&apos;ll verify the details and explain what happens next.</p></div>
                <span className="trust-badge"><ShieldIcon /><span><strong>Clear, consistent decisions</strong><small>Every outcome includes a reason</small></span></span>
              </section>

              <section className="request-layout">
                <article className="request-card">
                  <div className="card-heading"><span className="step-number">1</span><span><strong>Your return</strong><small>We found this order in your account</small></span></div>
                  <div className="order-product">
                    <span className={`product-visual product-${scenarioIndex}`} aria-hidden="true"><span /><span /><span /></span>
                    <span className="product-copy"><small>{scenario.orderNumber}</small><strong>{scenario.product}</strong><span>{scenario.sku} · Qty 1</span></span>
                    <span className="product-price"><strong>{scenario.refund}</strong><small>{scenario.orderAge}</small></span>
                    <span className="selected-check"><CheckIcon /></span>
                  </div>
                  <label className="message-label" htmlFor="return-message"><span><strong>What would you like us to know?</strong><small>Write naturally—no forms or reason codes needed.</small></span></label>
                  <textarea id="return-message" value={message} onChange={(event) => setMessage(event.target.value)} rows={4} />
                  <div className="request-footer">
                    <span className="privacy-note"><ShieldIcon />Your request is checked against your order and the current return policy.</span>
                    <button className="primary-button" disabled={!message.trim() || submitting} onClick={beginReturn} type="button">{submitting ? "Starting live workflow…" : "Review my return"}<ArrowIcon /></button>
                  </div>
                </article>

                <aside className="expectation-card">
                  <span className="eyebrow">What happens next</span>
                  <h2>A decision you can understand</h2>
                  <ol>
                    <li><span>1</span><div><strong>We verify your purchase</strong><small>Product, price, and timing come directly from your order.</small></div></li>
                    <li><span>2</span><div><strong>We check the current policy</strong><small>The exact policy section used is attached to the decision.</small></div></li>
                    <li><span>3</span><div><strong>We protect your account</strong><small>Duplicate refunds and unusual activity are checked automatically.</small></div></li>
                  </ol>
                  <div className="expectation-foot"><span>Usually completed in</span><strong>just a few seconds</strong></div>
                </aside>
              </section>
            </div>
          ) : (
            <div className="page-stack journey-page">
              <section className="journey-heading">
                <div><span className="eyebrow">Live decision journey</span><h1>{phase === "completed" ? "Your refund is on its way." : phase === "redirected" ? "This looks like a product question." : phase === "denied" ? "This return can’t move forward." : phase === "waiting" ? "A manager is reviewing your return." : phase === "recovery" ? "Recovery checkpoint saved." : "We’re reviewing your return."}</h1><p>{scenario.orderNumber} · {scenario.product} · {phase === "redirected" ? "no refund requested" : `requested refund ${scenario.refund}`}</p></div>
                <div className={`journey-state journey-${phase}`}><span>{phase === "completed" || phase === "redirected" ? <CheckIcon /> : phase === "denied" || phase === "recovery" ? "!" : phase === "waiting" ? "II" : <span className="large-spinner" />}</span><div><small>Current status</small><strong>{phase === "completed" ? "Refund issued" : phase === "redirected" ? "Request understood" : phase === "denied" ? "Decision complete" : phase === "waiting" ? "Waiting safely" : phase === "recovery" ? "Stopped safely" : "In progress"}</strong></div></div>
              </section>

              {phase === "completed" || phase === "redirected" || phase === "denied" ? (
                <section className={`outcome-banner outcome-${phase}`}>
                  <span className="outcome-icon">{phase === "completed" || phase === "redirected" ? <CheckIcon /> : "!"}</span>
                  <div><span className="eyebrow">{terminal.eyebrow}</span><h2>{terminal.heading}</h2><p>{terminal.detail}</p></div>
                  <button className="secondary-button" onClick={resetDemo} type="button">Start another demo</button>
                </section>
              ) : null}

              {phase === "recovery" ? (
                <section className="recovery-banner">
                  <span className="outcome-icon">!</span>
                  <div>
                    <span className="eyebrow">Injected failure reached</span>
                    <h2>{paymentStory ? "Provider accepted the refund; worker stopped before local completion" : "Successful sibling results are durable in CockroachDB"}</h2>
                    <p>{paymentStory
                      ? <>The provider recorded refund <strong>{providerRefund?.provider_refund_id ?? "pending"}</strong>. The worker released generation {snapshot?.lease_generation ?? 1}; resume will send the same idempotency key with a new worker.</>
                      : <>The worker released generation {snapshot?.lease_generation ?? 1}. Only <strong>{graphNodes.find((node) => node.id === recoveryNodeId)?.label}</strong> needs another attempt; no process is held open.</>}</p>
                    <small>Run {runId} · checkpoint {snapshot?.latest_checkpoint_id?.slice(0, 12)}…</small>
                  </div>
                  <div className="recovery-actions">
                    <button className="secondary-button" onClick={() => void copyInspectionSql()} type="button">{inspectionCopied ? "SQL copied" : "Copy database inspection SQL"}</button>
                    <button className="approve-button" disabled={submitting} onClick={() => void resumeRecovery()} type="button"><CheckIcon />Resume with a new worker</button>
                  </div>
                </section>
              ) : null}

              {paymentStory && providerRefund && (phase === "recovery" || phase === "completed") ? (
                <section className="payment-proof" aria-label="Payment idempotency proof">
                  <div><span className="eyebrow">Payment resilience proof</span><h2>{providerRefund.provider_refund_count} refund{providerRefund.provider_refund_count === 1 ? "" : "s"} issued. {providerRefund.request_count} provider request{providerRefund.request_count === 1 ? "" : "s"}. {Math.max(0, providerRefund.provider_refund_count - 1)} duplicate payments.</h2><p>The provider refund count comes from its durable ledger; the request counter records each call under the same key.</p></div>
                  <dl><div><dt>Provider refund ID</dt><dd>{providerRefund.provider_refund_id}</dd></div><div><dt>Idempotency key</dt><dd>{providerRefund.idempotency_key}</dd></div><div><dt>Local attempts</dt><dd>{snapshot?.refund_attempts.map((attempt) => `#${attempt.attempt_number} ${attempt.attempt_status}`).join(" · ") || "Pending"}</dd></div><div><dt>Audit</dt><dd>{snapshot?.audit_events.filter((event) => ["injected_failure_paused", "workflow_recovery_requested", "workflow_recovery_worker_claimed", "refund_succeeded"].includes(event.event_type)).map((event) => event.event_type).join(" · ") || "Pending"}</dd></div></dl>
                  <div className="payment-proof-links"><a href={traceLink ?? `${grafanaBase}/d/product-returns-graph-operations/product-returns-graph-operations`} target="_blank" rel="noreferrer">Open trace</a><a href={logsLink ?? `${grafanaBase}/d/product-returns-graph-operations/product-returns-graph-operations`} target="_blank" rel="noreferrer">Open run logs</a></div>
                </section>
              ) : null}

              <section className="journey-layout">
                <article className="graph-card">
                  <div className="section-heading"><div><span className="eyebrow">Behind the decision</span><h2>Return workflow</h2></div><span className="section-note"><i className={phase === "waiting" ? "paused" : ""} />{phase === "waiting" ? "Durably paused" : `${completedCount} steps complete`}</span></div>
                  <div className="graph-flow">
                    <NodeCard node={graphNodes[0]} scenario={scenario} output={actualNodeOutput(graphNodes[0], scenario, snapshot)} selected={selectedNodeId === "classify"} status={statusForNode("classify", phase, snapshot)} onSelect={() => setSelectedNodeId("classify")} />
                    <span className="flow-line vertical" />
                    <div className="parallel-round">
                      <span className="round-label">Parallel evidence round <small>Independent nodes · independent retry</small></span>
                      <div className="parallel-grid">
                        {graphNodes.slice(1, 4).map((node) => <NodeCard key={node.id} node={node} scenario={scenario} output={actualNodeOutput(node, scenario, snapshot)} selected={selectedNodeId === node.id} status={statusForNode(node.id, phase, snapshot)} onSelect={() => setSelectedNodeId(node.id)} />)}
                      </div>
                    </div>
                    <span className="flow-line vertical" />
                    <NodeCard node={graphNodes[4]} scenario={scenario} output={actualNodeOutput(graphNodes[4], scenario, snapshot)} selected={selectedNodeId === "decision"} status={statusForNode("decision", phase, snapshot)} onSelect={() => setSelectedNodeId("decision")} />
                    <div className="terminal-row">
                      {graphNodes.slice(5).map((node) => <NodeCard key={node.id} node={node} scenario={scenario} output={actualNodeOutput(node, scenario, snapshot)} selected={selectedNodeId === node.id} status={statusForNode(node.id, phase, snapshot)} onSelect={() => setSelectedNodeId(node.id)} />)}
                    </div>
                  </div>
                </article>

                <aside className="evidence-panel">
                  <div className="evidence-panel-heading"><span className="node-state complete"><CheckIcon /></span><span><small>Selected step</small><strong>{selectedNode.label}</strong></span></div>
                  <div className="io-block"><span>Input</span><p>{selectedNode.id === "classify" ? `“${message}”` : `Checkpointed state · ${scenario.orderNumber} · graph v${snapshot?.graph_version ?? "8"} · state ${snapshot?.state_version ?? 0}`}</p></div>
                  <div className="io-arrow"><ArrowIcon /></div>
                  <div className="io-block output"><span>Output</span><p>{actualNodeOutput(selectedNode, scenario, snapshot)}</p></div>
                  {detectedSafetyInsight ? <div className="ai-insight"><span>AI-detected customer insight</span><strong>Potential product-safety concern · {detectedSafetyInsight.category?.replaceAll("_", " ")}</strong><p>“{detectedSafetyInsight.supporting_text}”</p><small>Grounded in the customer’s words and recorded for follow-up. This insight does not independently change refund eligibility.</small></div> : null}
                  {selectedNode.id === "policy" ? <blockquote><span>Verified policy evidence</span><p>“{policyCitation?.quote ?? scenario.policyClause}”</p><cite>Standard Return and Refund Policy · version 1.0<br />{actualNodeOutput(selectedNode, scenario, snapshot)}</cite></blockquote> : null}
                  <dl className="technical-meta"><div><dt>Durability</dt><dd>{snapshot?.latest_checkpoint_id ? "Published checkpoint" : "CockroachDB run"}</dd></div><div><dt>Trace</dt><dd>{snapshot?.trace_id ? `${snapshot.trace_id.slice(0, 12)}…` : "Tempo correlated"}</dd></div><div><dt>Run</dt><dd>{runId ? `${runId.slice(0, 12)}…` : "Not started"}</dd></div><div><dt>Lease generation</dt><dd>{snapshot?.lease_generation ?? 0}{snapshot?.lease_owner ? " · held" : " · released"}</dd></div><div><dt>Attempt</dt><dd>{selectedAttempt ? `${selectedAttempt.attempt_number} · ${selectedAttempt.duration_ms ?? "…"} ms` : "Queued"}</dd></div></dl>
                  {runId ? <button className="inspection-button" onClick={() => void copyInspectionSql()} type="button"><DatabaseIcon />{inspectionCopied ? "SQL copied" : "Copy run-specific CockroachDB SQL"}</button> : null}
                  {phase === "waiting" ? <div className="manager-control"><span className="eyebrow">Presenter action</span><strong>Manager decision</strong><p>{snapshot?.approval?.approval_reason ?? "Manual review is required."} The worker has shut down; the decision will resume from this exact checkpoint.</p><div><button className="approve-button" disabled={submitting} onClick={() => void submitManagerDecision("approved")} type="button"><CheckIcon />Approve {scenario.refund}</button><button className="reject-button" disabled={submitting} onClick={() => void submitManagerDecision("rejected")} type="button">Reject</button></div></div> : null}
                </aside>
              </section>

              <section className="proof-strip">
                <span><CheckIcon /><span><strong>Exactly-once refund</strong><small>Provider idempotency key</small></span></span>
                <span><DatabaseIcon /><span><strong>Nothing held open</strong><small>Durable checkpoint + resume</small></span></span>
                <span><ShieldIcon /><span><strong>Complete audit trail</strong><small>What the graph knew at every step</small></span></span>
                <span><PulseIcon /><span><strong>Observable end to end</strong><small>Prometheus · Loki · Tempo</small></span></span>
              </section>
            </div>
          )}
        </main>

        <footer className="demo-disclaimer">All customers, orders, products, account signals, payment activity, and outcomes shown are synthetic. This concept demo is backed by LangGraph, LangChain, and CockroachDB.</footer>
      </div>
    </div>
  );
}
