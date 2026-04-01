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

  /**
   * Internal helper for REST endpoint calls with auth and error handling.
   */
  private async rest(
    method: string,
    path: string,
    options: { body?: unknown; params?: Record<string, any> } = {},
  ): Promise<any> {
    let url = path;
    if (options.params) {
      const filtered = Object.entries(options.params).filter(
        ([, v]) => v !== undefined && v !== null,
      );
      if (filtered.length > 0) {
        const qs = new URLSearchParams(
          filtered.map(([k, v]) => [k, String(v)]),
        ).toString();
        url = `${path}?${qs}`;
      }
    }
    const resp = await this.request(method, url, options.body);
    const data = await resp.json();
    if (!resp.ok) raiseForStatus(resp.status, data);
    return data;
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
    return this.rest("GET", `/v1/billing/wallets/${agentId}/balance`);
  }

  /** Deposit credits into a wallet. Returns new balance. */
  async deposit(agentId: string, amount: number, description = ""): Promise<number> {
    const r = await this.rest("POST", `/v1/billing/wallets/${agentId}/deposit`, {
      body: { amount, description },
    });
    return r.new_balance;
  }

  /** Get usage summary for an agent. */
  async getUsageSummary(
    agentId: string,
    since?: number,
  ): Promise<UsageSummaryResponse> {
    const params: Record<string, any> = {};
    if (since !== undefined) params.since = since;
    return this.rest("GET", `/v1/billing/wallets/${agentId}/usage`, { params });
  }

  /** Create a payment intent. */
  async createPaymentIntent(
    payer: string,
    payee: string,
    amount: number,
    description = "",
    idempotencyKey?: string,
  ): Promise<PaymentIntent> {
    // Note: idempotency key should be a header, but we keep it simple here
    return this.rest("POST", "/v1/payments/intents", {
      body: { payer, payee, amount, description },
    });
  }

  /** Capture a pending payment intent. */
  async capturePayment(intentId: string): Promise<PaymentIntent> {
    return this.rest("POST", `/v1/payments/intents/${intentId}/capture`);
  }

  /** Create an escrow. */
  async createEscrow(
    payer: string,
    payee: string,
    amount: number,
    description = "",
    timeoutHours?: number,
  ): Promise<EscrowResponse> {
    const body: Record<string, any> = { payer, payee, amount, description };
    if (timeoutHours !== undefined) body.timeout_hours = timeoutHours;
    return this.rest("POST", "/v1/payments/escrows", { body });
  }

  /** Release an escrow to the payee. */
  async releaseEscrow(escrowId: string): Promise<EscrowResponse> {
    return this.rest("POST", `/v1/payments/escrows/${escrowId}/release`);
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
    if (options.tags) params.tags = options.tags.join(",");
    if (options.maxCost !== undefined) params.max_cost = options.maxCost;
    const r = await this.rest("GET", "/v1/marketplace/services", { params });
    return r.services;
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
    const r = await this.rest("GET", "/v1/marketplace/match", { params });
    return r.matches;
  }

  /** Get trust score for a server. */
  async getTrustScore(
    serverId: string,
    window = "24h",
    recompute = false,
  ): Promise<TrustScore> {
    const params: Record<string, any> = { window };
    if (recompute) params.recompute = "true";
    return this.rest("GET", `/v1/trust/servers/${serverId}/score`, { params });
  }

  /** Get payment history for an agent. */
  async getPaymentHistory(
    agentId: string,
    limit = 100,
    offset = 0,
  ): Promise<PaymentHistoryResponse> {
    return this.rest("GET", "/v1/payments/history", {
      params: { agent_id: agentId, limit, offset },
    });
  }

  /** Register a new agent identity. */
  async registerAgent(
    agentId: string,
    displayName: string,
    capabilities: string[] = [],
  ): Promise<Record<string, any>> {
    return this.rest("POST", "/v1/identity/agents", {
      body: { agent_id: agentId, display_name: displayName, capabilities },
    });
  }

  /** Send a message between agents. */
  async sendMessage(
    sender: string,
    recipient: string,
    content: string,
    messageType = "text",
  ): Promise<Record<string, any>> {
    return this.rest("POST", "/v1/messaging/messages", {
      body: { sender, recipient, body: content, message_type: messageType },
    });
  }

  // ── Payment convenience methods ───────────────────────────────────

  /** Cancel a held escrow and refund the payer. */
  async cancelEscrow(escrowId: string): Promise<EscrowResponse> {
    return this.rest("POST", `/v1/payments/escrows/${escrowId}/cancel`);
  }

  /** Refund a settled payment (full or partial). */
  async refundSettlement(
    settlementId: string,
    options: { amount?: number; reason?: string } = {},
  ): Promise<RefundResponse> {
    const body: Record<string, any> = {};
    if (options.amount !== undefined) body.amount = options.amount;
    if (options.reason !== undefined) body.reason = options.reason;
    return this.rest("POST", `/v1/payments/settlements/${settlementId}/refund`, { body });
  }

  /** Refund a payment intent: voids if pending, reverse-transfers if settled. */
  async refundIntent(intentId: string): Promise<PaymentIntent> {
    return this.rest("POST", `/v1/payments/intents/${intentId}/refund`);
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
    const body: Record<string, any> = { payer, payee, amount, interval };
    if (options.description !== undefined) body.description = options.description;
    return this.rest("POST", "/v1/payments/subscriptions", { body });
  }

  /** Cancel an active or suspended subscription. */
  async cancelSubscription(
    subscriptionId: string,
    options: { cancelledBy?: string } = {},
  ): Promise<{ id: string; status: string }> {
    const body: Record<string, any> = {};
    if (options.cancelledBy !== undefined) body.cancelled_by = options.cancelledBy;
    return this.rest("POST", `/v1/payments/subscriptions/${subscriptionId}/cancel`, { body });
  }

  /** Get subscription details by ID. */
  async getSubscription(subscriptionId: string): Promise<SubscriptionDetailResponse> {
    return this.rest("GET", `/v1/payments/subscriptions/${subscriptionId}`);
  }

  /** List subscriptions for an agent. */
  async listSubscriptions(
    options: { agentId?: string; status?: string; limit?: number; offset?: number } = {},
  ): Promise<SubscriptionListResponse> {
    return this.rest("GET", "/v1/payments/subscriptions", {
      params: {
        agent_id: options.agentId,
        status: options.status,
        limit: options.limit,
        offset: options.offset,
      },
    });
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
    const body: Record<string, any> = {
      provider_id: options.providerId,
      name: options.name,
      description: options.description,
      category: options.category,
    };
    if (options.tools !== undefined) body.tools = options.tools;
    if (options.tags !== undefined) body.tags = options.tags;
    if (options.endpoint !== undefined) body.endpoint = options.endpoint;
    if (options.pricing !== undefined) body.pricing = options.pricing;
    return this.rest("POST", "/v1/marketplace/services", { body });
  }

  /** Get a marketplace service by ID. */
  async getService(serviceId: string): Promise<ServiceDetailResponse> {
    return this.rest("GET", `/v1/marketplace/services/${serviceId}`);
  }

  /** Rate a marketplace service (1-5). */
  async rateService(
    serviceId: string,
    agentId: string,
    rating: number,
    options: { review?: string } = {},
  ): Promise<ServiceRatingResponse> {
    const body: Record<string, any> = { agent_id: agentId, rating };
    if (options.review !== undefined) body.review = options.review;
    return this.rest("POST", `/v1/marketplace/services/${serviceId}/ratings`, { body });
  }

  // ── Trust convenience methods ─────────────────────────────────────

  /** Search for servers by name or minimum trust score. */
  async searchServers(
    options: { nameContains?: string; minScore?: number; limit?: number } = {},
  ): Promise<ServerSearchResponse> {
    return this.rest("GET", "/v1/trust/servers", {
      params: {
        name_contains: options.nameContains,
        min_score: options.minScore,
        limit: options.limit,
      },
    });
  }

  // ── Identity convenience methods ──────────────────────────────────

  /** Get the cryptographic identity for an agent. */
  async getAgentIdentity(agentId: string): Promise<AgentIdentityResponse> {
    return this.rest("GET", `/v1/identity/agents/${agentId}`);
  }

  /** Verify that a message was signed by the claimed agent. */
  async verifyAgent(
    agentId: string,
    message: string,
    signature: string,
  ): Promise<VerifyAgentResponse> {
    return this.rest("POST", `/v1/identity/agents/${agentId}/verify`, {
      body: { message, signature },
    });
  }

  /** Submit trading bot metrics for platform attestation. */
  async submitMetrics(
    agentId: string,
    metrics: Record<string, any>,
    options: { dataSource?: string } = {},
  ): Promise<MetricsSubmissionResponse> {
    const body: Record<string, any> = { metrics };
    if (options.dataSource !== undefined) body.data_source = options.dataSource;
    return this.rest("POST", `/v1/identity/agents/${agentId}/metrics`, { body });
  }

  /** Get all verified metric claims for an agent. */
  async getVerifiedClaims(agentId: string): Promise<VerifiedClaimsResponse> {
    return this.rest("GET", `/v1/identity/agents/${agentId}/claims`);
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
    const body: Record<string, any> = {
      url: options.url,
      event_types: options.eventTypes,
    };
    if (options.secret !== undefined) body.secret = options.secret;
    if (options.filterAgentIds !== undefined) body.filter_agent_ids = options.filterAgentIds;
    return this.rest("POST", "/v1/infra/webhooks", { body });
  }

  /** List all registered webhooks for an agent. */
  async listWebhooks(agentId: string): Promise<WebhookListResponse> {
    return this.rest("GET", "/v1/infra/webhooks");
  }

  /** Delete (deactivate) a webhook by ID. */
  async deleteWebhook(webhookId: string): Promise<WebhookDeleteResponse> {
    return this.rest("DELETE", `/v1/infra/webhooks/${webhookId}`);
  }

  // ── API key convenience methods ───────────────────────────────────

  /** Create a new API key for an agent. */
  async createApiKey(
    agentId: string,
    options: { tier?: string } = {},
  ): Promise<ApiKeyResponse> {
    const body: Record<string, any> = {};
    if (options.tier !== undefined) body.tier = options.tier;
    return this.rest("POST", "/v1/infra/keys", { body });
  }

  /** Rotate an API key: revoke current and create new with same tier. */
  async rotateKey(currentKey: string): Promise<KeyRotationResponse> {
    return this.rest("POST", "/v1/infra/keys/rotate", {
      body: { current_key: currentKey },
    });
  }

  // ── Event convenience methods ─────────────────────────────────────

  /** Publish an event to the cross-product event bus. */
  async publishEvent(
    eventType: string,
    source: string,
    payload: Record<string, any> = {},
  ): Promise<EventPublishResponse> {
    return this.rest("POST", "/v1/infra/events", {
      body: { event_type: eventType, source, payload },
    });
  }

  /** Query events from the event bus. */
  async getEvents(
    options: { eventType?: string; sinceId?: number; limit?: number } = {},
  ): Promise<EventListResponse> {
    return this.rest("GET", "/v1/infra/events", {
      params: {
        event_type: options.eventType,
        since_id: options.sinceId,
        limit: options.limit,
      },
    });
  }

  // ── Org convenience methods ───────────────────────────────────────

  /** Create a new organization. */
  async createOrg(orgName: string): Promise<OrgResponse> {
    return this.rest("POST", "/v1/identity/orgs", { body: { org_name: orgName } });
  }

  /** Get organization details and members. */
  async getOrg(orgId: string): Promise<OrgDetailResponse> {
    return this.rest("GET", `/v1/identity/orgs/${orgId}`);
  }

  /** Add an agent to an organization. */
  async addAgentToOrg(orgId: string, agentId: string): Promise<OrgMemberResponse> {
    return this.rest("POST", `/v1/identity/orgs/${orgId}/members`, {
      body: { agent_id: agentId },
    });
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
    const body: Record<string, any> = {
      initiator: options.initiator,
      responder: options.responder,
      amount: options.amount,
    };
    if (options.serviceId !== undefined) body.service_id = options.serviceId;
    if (options.expiresHours !== undefined) body.expires_hours = options.expiresHours;
    return this.rest("POST", "/v1/messaging/negotiations", { body });
  }

  /** Get messages for an agent. */
  async getMessages(
    agentId: string,
    options: { threadId?: string; limit?: number } = {},
  ): Promise<MessageListResponse> {
    return this.rest("GET", "/v1/messaging/messages", {
      params: { agent_id: agentId, thread_id: options.threadId, limit: options.limit },
    });
  }
}
