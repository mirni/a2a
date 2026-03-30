/**
 * A2A Commerce Gateway — TypeScript SDK Client.
 *
 * Zero-dependency client using native fetch (Node 18+).
 *
 * @example
 * ```ts
 * const client = new A2AClient({ apiKey: "ak_pro_..." });
 * const health = await client.health();
 * const balance = await client.getBalance("my-agent");
 * ```
 */

import {
  A2AError,
  RETRYABLE_STATUS_CODES,
  raiseForStatus,
} from "./errors";
import type {
  A2AClientOptions,
  AgentIdentityResponse,
  ApiKeyResponse,
  BalanceResponse,
  CheckoutResult,
  EscrowResponse,
  EventListResponse,
  EventPublishResponse,
  ExecuteResponse,
  HealthResponse,
  KeyRotationResponse,
  MessageListResponse,
  MetricsSubmissionResponse,
  NegotiationResponse,
  OrgDetailResponse,
  OrgMemberResponse,
  OrgResponse,
  PaymentHistoryResponse,
  PaymentIntent,
  RefundResponse,
  ServerSearchResponse,
  ServiceDetailResponse,
  ServiceRatingResponse,
  ServiceRegistrationResponse,
  SubscriptionDetailResponse,
  SubscriptionListResponse,
  SubscriptionResponse,
  ToolPricing,
  TrustScore,
  UsageSummaryResponse,
  VerifiedClaimsResponse,
  VerifyAgentResponse,
  WebhookDeleteResponse,
  WebhookListResponse,
  WebhookResponse,
} from "./types";

export class A2AClient {
  private readonly baseUrl: string;
  private readonly apiKey: string | undefined;
  private readonly timeout: number;
  private readonly maxRetries: number;
  private readonly retryBaseDelay: number;
  private readonly pricingCacheTtl: number;

  private pricingCache: ToolPricing[] | null = null;
  private pricingCacheTime = 0;

  constructor(options: A2AClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/+$/, "");
    this.apiKey = options.apiKey;
    this.timeout = options.timeout ?? 30_000;
    this.maxRetries = options.maxRetries ?? 3;
    this.retryBaseDelay = options.retryBaseDelay ?? 1_000;
    this.pricingCacheTtl = options.pricingCacheTtl ?? 300_000;
  }

  // ── Internal HTTP ──────────────────────────────────────────────────

  private headers(): Record<string, string> {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (this.apiKey) {
      h["Authorization"] = `Bearer ${this.apiKey}`;
    }
    return h;
  }

  private async request(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<Response> {
    let lastResponse: Response | undefined;

    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeout);

      try {
        const resp = await fetch(`${this.baseUrl}${path}`, {
          method,
          headers: this.headers(),
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });
        clearTimeout(timer);

        if (!RETRYABLE_STATUS_CODES.has(resp.status)) {
          return resp;
        }
        lastResponse = resp;

        if (attempt === this.maxRetries) {
          return resp;
        }
      } catch (err: any) {
        clearTimeout(timer);
        if (attempt === this.maxRetries) {
          throw new A2AError(
            `Request failed: ${err.message}`,
            "network_error",
          );
        }
      }

      // Exponential backoff
      let delay = this.retryBaseDelay * 2 ** attempt;

      // Respect Retry-After header on 429
      if (lastResponse?.status === 429) {
        const retryAfter = lastResponse.headers.get("retry-after");
        if (retryAfter) {
          const parsed = parseFloat(retryAfter);
          if (!isNaN(parsed)) {
            delay = Math.max(delay, parsed * 1000);
          }
        }
      }

      await new Promise((r) => setTimeout(r, delay));
    }

    // Should not reach here
    return lastResponse!;
  }

  // ── Core endpoints ─────────────────────────────────────────────────

  /** GET /v1/health */
  async health(): Promise<HealthResponse> {
    const resp = await this.request("GET", "/v1/health");
    if (!resp.ok) raiseForStatus(resp.status, await resp.json());
    return (await resp.json()) as HealthResponse;
  }

  /** GET /v1/pricing — full catalog (cached). */
  async pricing(useCache = true): Promise<ToolPricing[]> {
    const now = Date.now();
    if (
      useCache &&
      this.pricingCache !== null &&
      now - this.pricingCacheTime < this.pricingCacheTtl
    ) {
      return this.pricingCache;
    }

    const resp = await this.request("GET", "/v1/pricing");
    if (!resp.ok) raiseForStatus(resp.status, await resp.json());
    const data = (await resp.json()) as { tools: ToolPricing[] };

    this.pricingCache = data.tools;
    this.pricingCacheTime = now;
    return data.tools;
  }

  /** GET /v1/pricing/:tool — single tool pricing. */
  async pricingTool(toolName: string): Promise<ToolPricing> {
    const resp = await this.request("GET", `/v1/pricing/${toolName}`);
    const body = await resp.json();
    if (!resp.ok) raiseForStatus(resp.status, body);
    return body.tool as ToolPricing;
  }

  /** POST /v1/execute — execute a tool. */
  async execute(tool: string, params: Record<string, any> = {}): Promise<ExecuteResponse> {
    const resp = await this.request("POST", "/v1/execute", { tool, params });
    const body = await resp.json();
    if (!resp.ok) raiseForStatus(resp.status, body);
    return body as ExecuteResponse;
  }

  /** POST /v1/checkout — create a Stripe Checkout session. */
  async checkout(
    options: { package?: string; credits?: number; successUrl?: string; cancelUrl?: string },
  ): Promise<CheckoutResult> {
    const body: Record<string, any> = {};
    if (options.package) body.package = options.package;
    if (options.credits) body.credits = options.credits;
    if (options.successUrl) body.success_url = options.successUrl;
    if (options.cancelUrl) body.cancel_url = options.cancelUrl;

    const resp = await this.request("POST", "/v1/checkout", body);
    const data = await resp.json();
    if (!resp.ok) raiseForStatus(resp.status, data);
    return data.result as CheckoutResult;
  }

  /** Clear the pricing cache. */
  invalidatePricingCache(): void {
    this.pricingCache = null;
    this.pricingCacheTime = 0;
  }

  // ── Convenience wrappers ───────────────────────────────────────────

  /** Get wallet balance for an agent. */
  async getBalance(agentId: string): Promise<BalanceResponse> {
    const r = await this.execute("get_balance", { agent_id: agentId });
    return r.result as BalanceResponse;
  }

  /** Deposit credits into a wallet. Returns new balance. */
  async deposit(agentId: string, amount: number, description = ""): Promise<number> {
    const r = await this.execute("deposit", {
      agent_id: agentId,
      amount,
      description,
    });
    return r.result.new_balance;
  }

  /** Get usage summary for an agent. */
  async getUsageSummary(
    agentId: string,
    since?: number,
  ): Promise<UsageSummaryResponse> {
    const params: Record<string, any> = { agent_id: agentId };
    if (since !== undefined) params.since = since;
    const r = await this.execute("get_usage_summary", params);
    return r.result as UsageSummaryResponse;
  }

  /** Create a payment intent. */
  async createPaymentIntent(
    payer: string,
    payee: string,
    amount: number,
    description = "",
    idempotencyKey?: string,
  ): Promise<PaymentIntent> {
    const params: Record<string, any> = { payer, payee, amount, description };
    if (idempotencyKey) params.idempotency_key = idempotencyKey;
    const r = await this.execute("create_intent", params);
    return r.result as PaymentIntent;
  }

  /** Capture a pending payment intent. */
  async capturePayment(intentId: string): Promise<PaymentIntent> {
    const r = await this.execute("capture_intent", { intent_id: intentId });
    return r.result as PaymentIntent;
  }

  /** Create an escrow. */
  async createEscrow(
    payer: string,
    payee: string,
    amount: number,
    description = "",
    timeoutHours?: number,
  ): Promise<EscrowResponse> {
    const params: Record<string, any> = { payer, payee, amount, description };
    if (timeoutHours !== undefined) params.timeout_hours = timeoutHours;
    const r = await this.execute("create_escrow", params);
    return r.result as EscrowResponse;
  }

  /** Release an escrow to the payee. */
  async releaseEscrow(escrowId: string): Promise<EscrowResponse> {
    const r = await this.execute("release_escrow", { escrow_id: escrowId });
    return r.result as EscrowResponse;
  }

  /** Search the marketplace. */
  async searchServices(options: {
    query?: string;
    category?: string;
    tags?: string[];
    maxCost?: number;
    limit?: number;
  } = {}): Promise<Record<string, any>[]> {
    const params: Record<string, any> = { limit: options.limit ?? 20 };
    if (options.query) params.query = options.query;
    if (options.category) params.category = options.category;
    if (options.tags) params.tags = options.tags;
    if (options.maxCost !== undefined) params.max_cost = options.maxCost;
    const r = await this.execute("search_services", params);
    return r.result.services;
  }

  /** Find best matching services. */
  async bestMatch(
    query: string,
    options: {
      budget?: number;
      minTrustScore?: number;
      prefer?: string;
      limit?: number;
    } = {},
  ): Promise<Record<string, any>[]> {
    const params: Record<string, any> = {
      query,
      prefer: options.prefer ?? "trust",
      limit: options.limit ?? 5,
    };
    if (options.budget !== undefined) params.budget = options.budget;
    if (options.minTrustScore !== undefined)
      params.min_trust_score = options.minTrustScore;
    const r = await this.execute("best_match", params);
    return r.result.matches;
  }

  /** Get trust score for a server. */
  async getTrustScore(
    serverId: string,
    window = "24h",
    recompute = false,
  ): Promise<TrustScore> {
    const r = await this.execute("get_trust_score", {
      server_id: serverId,
      window,
      recompute,
    });
    return r.result as TrustScore;
  }

  /** Get payment history for an agent. */
  async getPaymentHistory(
    agentId: string,
    limit = 100,
    offset = 0,
  ): Promise<PaymentHistoryResponse> {
    const r = await this.execute("get_payment_history", {
      agent_id: agentId,
      limit,
      offset,
    });
    return r.result as PaymentHistoryResponse;
  }

  /** Register a new agent identity. */
  async registerAgent(
    agentId: string,
    displayName: string,
    capabilities: string[] = [],
  ): Promise<Record<string, any>> {
    const r = await this.execute("register_agent", {
      agent_id: agentId,
      display_name: displayName,
      capabilities,
    });
    return r.result;
  }

  /** Send a message between agents. */
  async sendMessage(
    sender: string,
    recipient: string,
    content: string,
    messageType = "text",
  ): Promise<Record<string, any>> {
    const r = await this.execute("send_message", {
      sender,
      recipient,
      content,
      message_type: messageType,
    });
    return r.result;
  }

  // ── Payment convenience methods ───────────────────────────────────

  /** Cancel a held escrow and refund the payer. */
  async cancelEscrow(escrowId: string): Promise<EscrowResponse> {
    const r = await this.execute("cancel_escrow", { escrow_id: escrowId });
    return r.result as EscrowResponse;
  }

  /** Refund a settled payment (full or partial). */
  async refundSettlement(
    settlementId: string,
    options: { amount?: number; reason?: string } = {},
  ): Promise<RefundResponse> {
    const params: Record<string, any> = { settlement_id: settlementId };
    if (options.amount !== undefined) params.amount = options.amount;
    if (options.reason !== undefined) params.reason = options.reason;
    const r = await this.execute("refund_settlement", params);
    return r.result as RefundResponse;
  }

  /** Refund a payment intent: voids if pending, reverse-transfers if settled. */
  async refundIntent(intentId: string): Promise<PaymentIntent> {
    const r = await this.execute("refund_intent", { intent_id: intentId });
    return r.result as PaymentIntent;
  }

  /** Void a pending payment (alias for refundIntent). */
  async voidPayment(intentId: string): Promise<PaymentIntent> {
    return this.refundIntent(intentId);
  }

  /** Create a recurring payment subscription. */
  async createSubscription(
    payer: string,
    payee: string,
    amount: number,
    interval: string,
    options: { description?: string } = {},
  ): Promise<SubscriptionResponse> {
    const params: Record<string, any> = { payer, payee, amount, interval };
    if (options.description !== undefined) params.description = options.description;
    const r = await this.execute("create_subscription", params);
    return r.result as SubscriptionResponse;
  }

  /** Cancel an active or suspended subscription. */
  async cancelSubscription(
    subscriptionId: string,
    options: { cancelledBy?: string } = {},
  ): Promise<{ id: string; status: string }> {
    const params: Record<string, any> = { subscription_id: subscriptionId };
    if (options.cancelledBy !== undefined) params.cancelled_by = options.cancelledBy;
    const r = await this.execute("cancel_subscription", params);
    return r.result as { id: string; status: string };
  }

  /** Get subscription details by ID. */
  async getSubscription(subscriptionId: string): Promise<SubscriptionDetailResponse> {
    const r = await this.execute("get_subscription", { subscription_id: subscriptionId });
    return r.result as SubscriptionDetailResponse;
  }

  /** List subscriptions for an agent. */
  async listSubscriptions(
    options: { agentId?: string; status?: string; limit?: number; offset?: number } = {},
  ): Promise<SubscriptionListResponse> {
    const params: Record<string, any> = {};
    if (options.agentId !== undefined) params.agent_id = options.agentId;
    if (options.status !== undefined) params.status = options.status;
    if (options.limit !== undefined) params.limit = options.limit;
    if (options.offset !== undefined) params.offset = options.offset;
    const r = await this.execute("list_subscriptions", params);
    return r.result as SubscriptionListResponse;
  }

  // ── Marketplace convenience methods ───────────────────────────────

  /** Register a new service in the marketplace. */
  async registerService(options: {
    providerId: string;
    name: string;
    description: string;
    category: string;
    tools?: string[];
    tags?: string[];
    endpoint?: string;
    pricing?: Record<string, any>;
  }): Promise<ServiceRegistrationResponse> {
    const params: Record<string, any> = {
      provider_id: options.providerId,
      name: options.name,
      description: options.description,
      category: options.category,
    };
    if (options.tools !== undefined) params.tools = options.tools;
    if (options.tags !== undefined) params.tags = options.tags;
    if (options.endpoint !== undefined) params.endpoint = options.endpoint;
    if (options.pricing !== undefined) params.pricing = options.pricing;
    const r = await this.execute("register_service", params);
    return r.result as ServiceRegistrationResponse;
  }

  /** Get a marketplace service by ID. */
  async getService(serviceId: string): Promise<ServiceDetailResponse> {
    const r = await this.execute("get_service", { service_id: serviceId });
    return r.result as ServiceDetailResponse;
  }

  /** Rate a marketplace service (1-5). */
  async rateService(
    serviceId: string,
    agentId: string,
    rating: number,
    options: { review?: string } = {},
  ): Promise<ServiceRatingResponse> {
    const params: Record<string, any> = { service_id: serviceId, agent_id: agentId, rating };
    if (options.review !== undefined) params.review = options.review;
    const r = await this.execute("rate_service", params);
    return r.result as ServiceRatingResponse;
  }

  // ── Trust convenience methods ─────────────────────────────────────

  /** Search for servers by name or minimum trust score. */
  async searchServers(
    options: { nameContains?: string; minScore?: number; limit?: number } = {},
  ): Promise<ServerSearchResponse> {
    const params: Record<string, any> = {};
    if (options.nameContains !== undefined) params.name_contains = options.nameContains;
    if (options.minScore !== undefined) params.min_score = options.minScore;
    if (options.limit !== undefined) params.limit = options.limit;
    const r = await this.execute("search_servers", params);
    return r.result as ServerSearchResponse;
  }

  // ── Identity convenience methods ──────────────────────────────────

  /** Get the cryptographic identity for an agent. */
  async getAgentIdentity(agentId: string): Promise<AgentIdentityResponse> {
    const r = await this.execute("get_agent_identity", { agent_id: agentId });
    return r.result as AgentIdentityResponse;
  }

  /** Verify that a message was signed by the claimed agent. */
  async verifyAgent(
    agentId: string,
    message: string,
    signature: string,
  ): Promise<VerifyAgentResponse> {
    const r = await this.execute("verify_agent", {
      agent_id: agentId,
      message,
      signature,
    });
    return r.result as VerifyAgentResponse;
  }

  /** Submit trading bot metrics for platform attestation. */
  async submitMetrics(
    agentId: string,
    metrics: Record<string, any>,
    options: { dataSource?: string } = {},
  ): Promise<MetricsSubmissionResponse> {
    const params: Record<string, any> = { agent_id: agentId, metrics };
    if (options.dataSource !== undefined) params.data_source = options.dataSource;
    const r = await this.execute("submit_metrics", params);
    return r.result as MetricsSubmissionResponse;
  }

  /** Get all verified metric claims for an agent. */
  async getVerifiedClaims(agentId: string): Promise<VerifiedClaimsResponse> {
    const r = await this.execute("get_verified_claims", { agent_id: agentId });
    return r.result as VerifiedClaimsResponse;
  }

  // ── Webhook convenience methods ───────────────────────────────────

  /** Register a webhook endpoint. */
  async registerWebhook(options: {
    agentId: string;
    url: string;
    eventTypes: string[];
    secret?: string;
    filterAgentIds?: string[];
  }): Promise<WebhookResponse> {
    const params: Record<string, any> = {
      agent_id: options.agentId,
      url: options.url,
      event_types: options.eventTypes,
    };
    if (options.secret !== undefined) params.secret = options.secret;
    if (options.filterAgentIds !== undefined) params.filter_agent_ids = options.filterAgentIds;
    const r = await this.execute("register_webhook", params);
    return r.result as WebhookResponse;
  }

  /** List all registered webhooks for an agent. */
  async listWebhooks(agentId: string): Promise<WebhookListResponse> {
    const r = await this.execute("list_webhooks", { agent_id: agentId });
    return r.result as WebhookListResponse;
  }

  /** Delete (deactivate) a webhook by ID. */
  async deleteWebhook(webhookId: string): Promise<WebhookDeleteResponse> {
    const r = await this.execute("delete_webhook", { webhook_id: webhookId });
    return r.result as WebhookDeleteResponse;
  }

  // ── API key convenience methods ───────────────────────────────────

  /** Create a new API key for an agent. */
  async createApiKey(
    agentId: string,
    options: { tier?: string } = {},
  ): Promise<ApiKeyResponse> {
    const params: Record<string, any> = { agent_id: agentId };
    if (options.tier !== undefined) params.tier = options.tier;
    const r = await this.execute("create_api_key", params);
    return r.result as ApiKeyResponse;
  }

  /** Rotate an API key: revoke current and create new with same tier. */
  async rotateKey(currentKey: string): Promise<KeyRotationResponse> {
    const r = await this.execute("rotate_key", { current_key: currentKey });
    return r.result as KeyRotationResponse;
  }

  // ── Event convenience methods ─────────────────────────────────────

  /** Publish an event to the cross-product event bus. */
  async publishEvent(
    eventType: string,
    source: string,
    payload: Record<string, any> = {},
  ): Promise<EventPublishResponse> {
    const r = await this.execute("publish_event", {
      event_type: eventType,
      source,
      payload,
    });
    return r.result as EventPublishResponse;
  }

  /** Query events from the event bus. */
  async getEvents(
    options: { eventType?: string; sinceId?: number; limit?: number } = {},
  ): Promise<EventListResponse> {
    const params: Record<string, any> = {};
    if (options.eventType !== undefined) params.event_type = options.eventType;
    if (options.sinceId !== undefined) params.since_id = options.sinceId;
    if (options.limit !== undefined) params.limit = options.limit;
    const r = await this.execute("get_events", params);
    return r.result as EventListResponse;
  }

  // ── Org convenience methods ───────────────────────────────────────

  /** Create a new organization. */
  async createOrg(orgName: string): Promise<OrgResponse> {
    const r = await this.execute("create_org", { org_name: orgName });
    return r.result as OrgResponse;
  }

  /** Get organization details and members. */
  async getOrg(orgId: string): Promise<OrgDetailResponse> {
    const r = await this.execute("get_org", { org_id: orgId });
    return r.result as OrgDetailResponse;
  }

  /** Add an agent to an organization. */
  async addAgentToOrg(orgId: string, agentId: string): Promise<OrgMemberResponse> {
    const r = await this.execute("add_agent_to_org", { org_id: orgId, agent_id: agentId });
    return r.result as OrgMemberResponse;
  }

  /** Get organization members (convenience alias for getOrg). */
  async getOrgMembers(orgId: string): Promise<OrgDetailResponse> {
    return this.getOrg(orgId);
  }

  // ── Messaging convenience methods ─────────────────────────────────

  /** Start a price negotiation with another agent. */
  async negotiatePrice(options: {
    initiator: string;
    responder: string;
    amount: number;
    serviceId?: string;
    expiresHours?: number;
  }): Promise<NegotiationResponse> {
    const params: Record<string, any> = {
      initiator: options.initiator,
      responder: options.responder,
      amount: options.amount,
    };
    if (options.serviceId !== undefined) params.service_id = options.serviceId;
    if (options.expiresHours !== undefined) params.expires_hours = options.expiresHours;
    const r = await this.execute("negotiate_price", params);
    return r.result as NegotiationResponse;
  }

  /** Get messages for an agent. */
  async getMessages(
    agentId: string,
    options: { threadId?: string; limit?: number } = {},
  ): Promise<MessageListResponse> {
    const params: Record<string, any> = { agent_id: agentId };
    if (options.threadId !== undefined) params.thread_id = options.threadId;
    if (options.limit !== undefined) params.limit = options.limit;
    const r = await this.execute("get_messages", params);
    return r.result as MessageListResponse;
  }
}
