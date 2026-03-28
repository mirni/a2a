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
  CheckoutResult,
  Escrow,
  ExecuteResponse,
  HealthResponse,
  PaymentIntent,
  ToolPricing,
  TrustScore,
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
  async getBalance(agentId: string): Promise<number> {
    const r = await this.execute("get_balance", { agent_id: agentId });
    return r.result.balance;
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
  ): Promise<Record<string, any>> {
    const params: Record<string, any> = { agent_id: agentId };
    if (since !== undefined) params.since = since;
    const r = await this.execute("get_usage_summary", params);
    return r.result;
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
  ): Promise<Escrow> {
    const params: Record<string, any> = { payer, payee, amount, description };
    if (timeoutHours !== undefined) params.timeout_hours = timeoutHours;
    const r = await this.execute("create_escrow", params);
    return r.result as Escrow;
  }

  /** Release an escrow to the payee. */
  async releaseEscrow(escrowId: string): Promise<Escrow> {
    const r = await this.execute("release_escrow", { escrow_id: escrowId });
    return r.result as Escrow;
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
  ): Promise<Record<string, any>[]> {
    const r = await this.execute("get_payment_history", {
      agent_id: agentId,
      limit,
      offset,
    });
    return r.result.history;
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
}
