/**
 * Tests for ALL convenience methods (Items 4, 11, 12).
 *
 * Each test verifies:
 * 1. The method exists on A2AClient
 * 2. It calls execute() with the correct tool name and params
 * 3. It returns a properly typed response
 *
 * Uses a mock HTTP server to capture actual execute() calls.
 */

import { describe, it, before, after } from "node:test";
import * as assert from "node:assert/strict";
import * as http from "node:http";

import { A2AClient } from "../client";
import type {
  BalanceResponse,
  UsageSummaryResponse,
  PaymentHistoryResponse,
  PaymentIntent,
  Escrow,
  EscrowResponse,
  RefundResponse,
  SubscriptionResponse,
  SubscriptionDetailResponse,
  SubscriptionListResponse,
  ServiceRegistrationResponse,
  ServiceDetailResponse,
  ServiceRatingResponse,
  TrustScore,
  ServerSearchResponse,
  AgentIdentityResponse,
  VerifyAgentResponse,
  MetricsSubmissionResponse,
  VerifiedClaimsResponse,
  WebhookResponse,
  WebhookListResponse,
  WebhookDeleteResponse,
  ApiKeyResponse,
  KeyRotationResponse,
  EventPublishResponse,
  EventListResponse,
  OrgResponse,
  OrgDetailResponse,
  OrgMemberResponse,
  NegotiationResponse,
  MessageListResponse,
} from "../types";

// ---------------------------------------------------------------------------
// Test HTTP server — captures execute() calls
// ---------------------------------------------------------------------------

let server: http.Server;
let baseUrl: string;
let lastExecuteCall: { tool: string; params: Record<string, any> } | null = null;
let executeResult: Record<string, any> = {};

before(async () => {
  server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (chunk: Buffer) => { body += chunk.toString(); });
    req.on("end", () => {
      if (req.method === "POST" && req.url === "/v1/execute") {
        const parsed = JSON.parse(body);
        lastExecuteCall = { tool: parsed.tool, params: parsed.params };
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ success: true, result: executeResult, charged: 0 }));
      } else {
        res.writeHead(404);
        res.end(JSON.stringify({ error: { code: "not_found", message: "not found" } }));
      }
    });
  });

  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address() as any;
      baseUrl = `http://127.0.0.1:${addr.port}`;
      resolve();
    });
  });
});

after(async () => {
  await new Promise<void>((resolve) => server.close(() => resolve()));
});

function client(): A2AClient {
  return new A2AClient({ baseUrl, apiKey: "test-key" });
}

// ---------------------------------------------------------------------------
// Payment tools
// ---------------------------------------------------------------------------

describe("Payment convenience methods", () => {
  it("cancelEscrow calls cancel_escrow with escrow_id and returns EscrowResponse", async () => {
    executeResult = { id: "esc-1", status: "cancelled", amount: 50 };
    const result: EscrowResponse = await client().cancelEscrow("esc-1");
    assert.equal(lastExecuteCall?.tool, "cancel_escrow");
    assert.equal(lastExecuteCall?.params.escrow_id, "esc-1");
    assert.equal(result.id, "esc-1");
    assert.equal(result.status, "cancelled");
    assert.equal(result.amount, 50);
  });

  it("refundSettlement calls refund_settlement with correct params and returns RefundResponse", async () => {
    executeResult = { id: "ref-1", settlement_id: "set-1", amount: 25, reason: "defective", status: "refunded" };
    const result: RefundResponse = await client().refundSettlement("set-1", { amount: 25, reason: "defective" });
    assert.equal(lastExecuteCall?.tool, "refund_settlement");
    assert.equal(lastExecuteCall?.params.settlement_id, "set-1");
    assert.equal(lastExecuteCall?.params.amount, 25);
    assert.equal(lastExecuteCall?.params.reason, "defective");
    assert.equal(result.id, "ref-1");
    assert.equal(result.status, "refunded");
    assert.equal(result.settlement_id, "set-1");
  });

  it("refundSettlement works without optional params", async () => {
    executeResult = { id: "ref-2", settlement_id: "set-2", amount: 100, status: "refunded" };
    const result: RefundResponse = await client().refundSettlement("set-2");
    assert.equal(lastExecuteCall?.tool, "refund_settlement");
    assert.equal(lastExecuteCall?.params.settlement_id, "set-2");
    assert.equal(lastExecuteCall?.params.amount, undefined);
    assert.equal(result.amount, 100);
  });

  it("refundIntent calls refund_intent with intent_id and returns PaymentIntent", async () => {
    executeResult = { id: "int-1", status: "refunded", amount: 30 };
    const result: PaymentIntent = await client().refundIntent("int-1");
    assert.equal(lastExecuteCall?.tool, "refund_intent");
    assert.equal(lastExecuteCall?.params.intent_id, "int-1");
    assert.equal(result.id, "int-1");
    assert.equal(result.status, "refunded");
  });

  it("voidPayment is an alias for refundIntent", async () => {
    executeResult = { id: "int-2", status: "voided", amount: 15 };
    const result: PaymentIntent = await client().voidPayment("int-2");
    assert.equal(lastExecuteCall?.tool, "refund_intent");
    assert.equal(lastExecuteCall?.params.intent_id, "int-2");
    assert.equal(result.id, "int-2");
  });

  it("createSubscription calls create_subscription with correct params and returns SubscriptionResponse", async () => {
    executeResult = { id: "sub-1", status: "active", amount: 10, interval: "monthly", next_charge_at: 1234567890 };
    const result: SubscriptionResponse = await client().createSubscription(
      "payer-1", "payee-1", 10, "monthly", { description: "monthly plan" },
    );
    assert.equal(lastExecuteCall?.tool, "create_subscription");
    assert.equal(lastExecuteCall?.params.payer, "payer-1");
    assert.equal(lastExecuteCall?.params.payee, "payee-1");
    assert.equal(lastExecuteCall?.params.amount, 10);
    assert.equal(lastExecuteCall?.params.interval, "monthly");
    assert.equal(lastExecuteCall?.params.description, "monthly plan");
    assert.equal(result.id, "sub-1");
    assert.equal(result.interval, "monthly");
  });

  it("cancelSubscription calls cancel_subscription and returns { id, status }", async () => {
    executeResult = { id: "sub-1", status: "cancelled" };
    const result = await client().cancelSubscription("sub-1", { cancelledBy: "agent-1" });
    assert.equal(lastExecuteCall?.tool, "cancel_subscription");
    assert.equal(lastExecuteCall?.params.subscription_id, "sub-1");
    assert.equal(lastExecuteCall?.params.cancelled_by, "agent-1");
    assert.equal(result.id, "sub-1");
    assert.equal(result.status, "cancelled");
  });

  it("getSubscription calls get_subscription and returns SubscriptionDetailResponse", async () => {
    executeResult = {
      id: "sub-1", payer: "p1", payee: "p2", amount: 10,
      interval: "daily", status: "active", next_charge_at: 123, charge_count: 5, created_at: 100,
    };
    const result: SubscriptionDetailResponse = await client().getSubscription("sub-1");
    assert.equal(lastExecuteCall?.tool, "get_subscription");
    assert.equal(lastExecuteCall?.params.subscription_id, "sub-1");
    assert.equal(result.payer, "p1");
    assert.equal(result.charge_count, 5);
  });

  it("listSubscriptions calls list_subscriptions and returns SubscriptionListResponse", async () => {
    executeResult = { subscriptions: [{ id: "sub-1" }, { id: "sub-2" }] };
    const result: SubscriptionListResponse = await client().listSubscriptions({ agentId: "agent-1", status: "active" });
    assert.equal(lastExecuteCall?.tool, "list_subscriptions");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(lastExecuteCall?.params.status, "active");
    assert.equal(result.subscriptions.length, 2);
  });
});

// ---------------------------------------------------------------------------
// Marketplace tools
// ---------------------------------------------------------------------------

describe("Marketplace convenience methods", () => {
  it("registerService calls register_service with correct params", async () => {
    executeResult = { id: "svc-1", name: "My Service", status: "active" };
    const result: ServiceRegistrationResponse = await client().registerService({
      providerId: "agent-1",
      name: "My Service",
      description: "A cool service",
      category: "ai",
      tools: ["tool1"],
      tags: ["fast"],
      endpoint: "https://example.com",
      pricing: { model: "per_call", cost: 0.01 },
    });
    assert.equal(lastExecuteCall?.tool, "register_service");
    assert.equal(lastExecuteCall?.params.provider_id, "agent-1");
    assert.equal(lastExecuteCall?.params.name, "My Service");
    assert.equal(lastExecuteCall?.params.category, "ai");
    assert.deepEqual(lastExecuteCall?.params.tools, ["tool1"]);
    assert.equal(result.id, "svc-1");
    assert.equal(result.status, "active");
  });

  it("getService calls get_service with service_id", async () => {
    executeResult = { id: "svc-1", name: "Test", description: "desc", category: "ai", status: "active" };
    const result: ServiceDetailResponse = await client().getService("svc-1");
    assert.equal(lastExecuteCall?.tool, "get_service");
    assert.equal(lastExecuteCall?.params.service_id, "svc-1");
    assert.equal(result.id, "svc-1");
    assert.equal(result.category, "ai");
  });

  it("rateService calls rate_service with correct params", async () => {
    executeResult = { service_id: "svc-1", agent_id: "agent-1", rating: 5 };
    const result: ServiceRatingResponse = await client().rateService("svc-1", "agent-1", 5, { review: "Great!" });
    assert.equal(lastExecuteCall?.tool, "rate_service");
    assert.equal(lastExecuteCall?.params.service_id, "svc-1");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(lastExecuteCall?.params.rating, 5);
    assert.equal(lastExecuteCall?.params.review, "Great!");
    assert.equal(result.rating, 5);
  });
});

// ---------------------------------------------------------------------------
// Trust tools
// ---------------------------------------------------------------------------

describe("Trust convenience methods", () => {
  it("searchServers calls search_servers with correct params", async () => {
    executeResult = { servers: [{ id: "srv-1", name: "Test Server", url: "https://test.com" }] };
    const result: ServerSearchResponse = await client().searchServers({ nameContains: "Test", minScore: 0.8, limit: 10 });
    assert.equal(lastExecuteCall?.tool, "search_servers");
    assert.equal(lastExecuteCall?.params.name_contains, "Test");
    assert.equal(lastExecuteCall?.params.min_score, 0.8);
    assert.equal(lastExecuteCall?.params.limit, 10);
    assert.equal(result.servers.length, 1);
    assert.equal(result.servers[0].id, "srv-1");
  });
});

// ---------------------------------------------------------------------------
// Identity tools
// ---------------------------------------------------------------------------

describe("Identity convenience methods", () => {
  it("getAgentIdentity calls get_agent_identity with agent_id", async () => {
    executeResult = { agent_id: "agent-1", public_key: "abc123", created_at: 1000, org_id: "org-1", found: true };
    const result: AgentIdentityResponse = await client().getAgentIdentity("agent-1");
    assert.equal(lastExecuteCall?.tool, "get_agent_identity");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(result.agent_id, "agent-1");
    assert.equal(result.public_key, "abc123");
    assert.equal(result.found, true);
  });

  it("verifyAgent calls verify_agent with correct params", async () => {
    executeResult = { valid: true };
    const result: VerifyAgentResponse = await client().verifyAgent("agent-1", "hello", "sig123");
    assert.equal(lastExecuteCall?.tool, "verify_agent");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(lastExecuteCall?.params.message, "hello");
    assert.equal(lastExecuteCall?.params.signature, "sig123");
    assert.equal(result.valid, true);
  });

  it("submitMetrics calls submit_metrics with correct params", async () => {
    executeResult = {
      agent_id: "agent-1", commitment_hashes: ["h1"], verified_at: 100,
      valid_until: 200, data_source: "self_reported", signature: "sig",
    };
    const result: MetricsSubmissionResponse = await client().submitMetrics(
      "agent-1", { sharpe_30d: 2.35 }, { dataSource: "self_reported" },
    );
    assert.equal(lastExecuteCall?.tool, "submit_metrics");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.deepEqual(lastExecuteCall?.params.metrics, { sharpe_30d: 2.35 });
    assert.equal(lastExecuteCall?.params.data_source, "self_reported");
    assert.equal(result.agent_id, "agent-1");
    assert.deepEqual(result.commitment_hashes, ["h1"]);
  });

  it("getVerifiedClaims calls get_verified_claims with agent_id", async () => {
    executeResult = { claims: [{ agent_id: "a1", metric_name: "sharpe", claim_type: "gte", bound_value: 2, valid_until: 999 }] };
    const result: VerifiedClaimsResponse = await client().getVerifiedClaims("agent-1");
    assert.equal(lastExecuteCall?.tool, "get_verified_claims");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(result.claims.length, 1);
    assert.equal(result.claims[0].metric_name, "sharpe");
  });
});

// ---------------------------------------------------------------------------
// Webhook tools
// ---------------------------------------------------------------------------

describe("Webhook convenience methods", () => {
  it("registerWebhook calls register_webhook with correct params", async () => {
    executeResult = {
      id: "wh-1", agent_id: "agent-1", url: "https://hook.example.com",
      event_types: ["billing.deposit"], filter_agent_ids: null, created_at: 100, active: true,
    };
    const result: WebhookResponse = await client().registerWebhook({
      agentId: "agent-1",
      url: "https://hook.example.com",
      eventTypes: ["billing.deposit"],
      secret: "s3cret",
    });
    assert.equal(lastExecuteCall?.tool, "register_webhook");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(lastExecuteCall?.params.url, "https://hook.example.com");
    assert.deepEqual(lastExecuteCall?.params.event_types, ["billing.deposit"]);
    assert.equal(lastExecuteCall?.params.secret, "s3cret");
    assert.equal(result.id, "wh-1");
    assert.equal(result.active, true);
  });

  it("listWebhooks calls list_webhooks with agent_id", async () => {
    executeResult = { webhooks: [{ id: "wh-1" }, { id: "wh-2" }] };
    const result: WebhookListResponse = await client().listWebhooks("agent-1");
    assert.equal(lastExecuteCall?.tool, "list_webhooks");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(result.webhooks.length, 2);
  });

  it("deleteWebhook calls delete_webhook with webhook_id", async () => {
    executeResult = { deleted: true };
    const result: WebhookDeleteResponse = await client().deleteWebhook("wh-1");
    assert.equal(lastExecuteCall?.tool, "delete_webhook");
    assert.equal(lastExecuteCall?.params.webhook_id, "wh-1");
    assert.equal(result.deleted, true);
  });
});

// ---------------------------------------------------------------------------
// API key tools
// ---------------------------------------------------------------------------

describe("API key convenience methods", () => {
  it("createApiKey calls create_api_key with correct params", async () => {
    executeResult = { key: "ak_pro_abc", agent_id: "agent-1", tier: "pro", created_at: 100 };
    const result: ApiKeyResponse = await client().createApiKey("agent-1", { tier: "pro" });
    assert.equal(lastExecuteCall?.tool, "create_api_key");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(lastExecuteCall?.params.tier, "pro");
    assert.equal(result.key, "ak_pro_abc");
    assert.equal(result.tier, "pro");
  });

  it("rotateKey calls rotate_key with current_key", async () => {
    executeResult = { new_key: "ak_pro_xyz", tier: "pro", agent_id: "agent-1", revoked: true };
    const result: KeyRotationResponse = await client().rotateKey("ak_pro_old");
    assert.equal(lastExecuteCall?.tool, "rotate_key");
    assert.equal(lastExecuteCall?.params.current_key, "ak_pro_old");
    assert.equal(result.new_key, "ak_pro_xyz");
    assert.equal(result.revoked, true);
  });
});

// ---------------------------------------------------------------------------
// Event tools
// ---------------------------------------------------------------------------

describe("Event convenience methods", () => {
  it("publishEvent calls publish_event with correct params", async () => {
    executeResult = { event_id: 42 };
    const result: EventPublishResponse = await client().publishEvent("trust.score_drop", "trust", { server_id: "srv-1" });
    assert.equal(lastExecuteCall?.tool, "publish_event");
    assert.equal(lastExecuteCall?.params.event_type, "trust.score_drop");
    assert.equal(lastExecuteCall?.params.source, "trust");
    assert.deepEqual(lastExecuteCall?.params.payload, { server_id: "srv-1" });
    assert.equal(result.event_id, 42);
  });

  it("getEvents calls get_events with correct params", async () => {
    executeResult = { events: [{ id: 1, event_type: "test", source: "test", payload: {}, integrity_hash: "abc", created_at: "2024-01-01" }] };
    const result: EventListResponse = await client().getEvents({ eventType: "test", sinceId: 0, limit: 50 });
    assert.equal(lastExecuteCall?.tool, "get_events");
    assert.equal(lastExecuteCall?.params.event_type, "test");
    assert.equal(lastExecuteCall?.params.since_id, 0);
    assert.equal(lastExecuteCall?.params.limit, 50);
    assert.equal(result.events.length, 1);
  });

  it("getEvents works without params", async () => {
    executeResult = { events: [] };
    const result: EventListResponse = await client().getEvents();
    assert.equal(lastExecuteCall?.tool, "get_events");
    assert.equal(result.events.length, 0);
  });
});

// ---------------------------------------------------------------------------
// Org tools
// ---------------------------------------------------------------------------

describe("Org convenience methods", () => {
  it("createOrg calls create_org with org_name", async () => {
    executeResult = { org_id: "org-1", name: "My Org", created_at: 100 };
    const result: OrgResponse = await client().createOrg("My Org");
    assert.equal(lastExecuteCall?.tool, "create_org");
    assert.equal(lastExecuteCall?.params.org_name, "My Org");
    assert.equal(result.org_id, "org-1");
    assert.equal(result.name, "My Org");
  });

  it("getOrg calls get_org with org_id", async () => {
    executeResult = { org_id: "org-1", name: "My Org", created_at: 100, members: ["a1", "a2"] };
    const result: OrgDetailResponse = await client().getOrg("org-1");
    assert.equal(lastExecuteCall?.tool, "get_org");
    assert.equal(lastExecuteCall?.params.org_id, "org-1");
    assert.equal(result.org_id, "org-1");
    assert.equal(result.members.length, 2);
  });

  it("addAgentToOrg calls add_agent_to_org with correct params", async () => {
    executeResult = { agent_id: "agent-1", org_id: "org-1" };
    const result: OrgMemberResponse = await client().addAgentToOrg("org-1", "agent-1");
    assert.equal(lastExecuteCall?.tool, "add_agent_to_org");
    assert.equal(lastExecuteCall?.params.org_id, "org-1");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(result.agent_id, "agent-1");
    assert.equal(result.org_id, "org-1");
  });

  it("getOrgMembers calls get_org and extracts members", async () => {
    executeResult = { org_id: "org-1", name: "My Org", created_at: 100, members: ["a1", "a2", "a3"] };
    const result: OrgDetailResponse = await client().getOrgMembers("org-1");
    assert.equal(lastExecuteCall?.tool, "get_org");
    assert.equal(lastExecuteCall?.params.org_id, "org-1");
    assert.equal(result.members.length, 3);
  });
});

// ---------------------------------------------------------------------------
// Messaging tools
// ---------------------------------------------------------------------------

describe("Messaging convenience methods", () => {
  it("negotiatePrice calls negotiate_price with correct params", async () => {
    executeResult = { negotiation_id: "neg-1", thread_id: "thr-1", status: "pending", proposed_amount: 50 };
    const result: NegotiationResponse = await client().negotiatePrice({
      initiator: "agent-1",
      responder: "agent-2",
      amount: 50,
      serviceId: "svc-1",
      expiresHours: 48,
    });
    assert.equal(lastExecuteCall?.tool, "negotiate_price");
    assert.equal(lastExecuteCall?.params.initiator, "agent-1");
    assert.equal(lastExecuteCall?.params.responder, "agent-2");
    assert.equal(lastExecuteCall?.params.amount, 50);
    assert.equal(lastExecuteCall?.params.service_id, "svc-1");
    assert.equal(lastExecuteCall?.params.expires_hours, 48);
    assert.equal(result.negotiation_id, "neg-1");
  });

  it("getMessages calls get_messages with correct params", async () => {
    executeResult = { messages: [{ id: "msg-1" }, { id: "msg-2" }] };
    const result: MessageListResponse = await client().getMessages("agent-1", { threadId: "thr-1", limit: 25 });
    assert.equal(lastExecuteCall?.tool, "get_messages");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(lastExecuteCall?.params.thread_id, "thr-1");
    assert.equal(lastExecuteCall?.params.limit, 25);
    assert.equal(result.messages.length, 2);
  });

  it("getMessages works with only agentId", async () => {
    executeResult = { messages: [] };
    const result: MessageListResponse = await client().getMessages("agent-1");
    assert.equal(lastExecuteCall?.tool, "get_messages");
    assert.equal(lastExecuteCall?.params.agent_id, "agent-1");
    assert.equal(result.messages.length, 0);
  });
});

// ---------------------------------------------------------------------------
// Typed responses for existing methods (Item 12 validation)
// ---------------------------------------------------------------------------

describe("Typed responses for existing methods", () => {
  it("getBalance returns BalanceResponse", async () => {
    executeResult = { balance: 99.5 };
    const result: BalanceResponse = await client().getBalance("agent-1");
    assert.equal(result.balance, 99.5);
  });

  it("getUsageSummary returns UsageSummaryResponse", async () => {
    executeResult = { total_cost: 10.5, total_calls: 100, total_tokens: 5000 };
    const result: UsageSummaryResponse = await client().getUsageSummary("agent-1");
    assert.equal(result.total_cost, 10.5);
    assert.equal(result.total_calls, 100);
    assert.equal(result.total_tokens, 5000);
  });

  it("getPaymentHistory returns PaymentHistoryResponse", async () => {
    executeResult = { history: [{ id: "ph-1" }] };
    const result: PaymentHistoryResponse = await client().getPaymentHistory("agent-1");
    assert.equal(result.history.length, 1);
  });

  it("releaseEscrow returns EscrowResponse", async () => {
    executeResult = { id: "esc-1", status: "released", amount: 100 };
    const result: EscrowResponse = await client().releaseEscrow("esc-1");
    assert.equal(result.id, "esc-1");
    assert.equal(result.status, "released");
    assert.equal(result.amount, 100);
  });

  it("createEscrow returns EscrowResponse", async () => {
    executeResult = { id: "esc-2", status: "held", amount: 200 };
    const result: EscrowResponse = await client().createEscrow("p1", "p2", 200);
    assert.equal(result.id, "esc-2");
    assert.equal(result.status, "held");
  });

  it("getTrustScore returns TrustScore", async () => {
    executeResult = {
      server_id: "srv-1", composite_score: 0.95, reliability_score: 0.9,
      security_score: 0.88, documentation_score: 0.92, responsiveness_score: 0.85,
      confidence: 0.75, window: "24h",
    };
    const result: TrustScore = await client().getTrustScore("srv-1");
    assert.equal(result.server_id, "srv-1");
    assert.equal(result.composite_score, 0.95);
  });
});
