/** Response types for the A2A Commerce Gateway SDK. */

export interface ExecuteResponse {
  success: boolean;
  result: Record<string, any>;
  charged: number;
}

export interface HealthResponse {
  status: string;
  version: string;
  tools: number;
}

export interface ToolPricing {
  name: string;
  service: string;
  description: string;
  pricing: Record<string, any>;
  tier_required: string;
  input_schema?: Record<string, any>;
  output_schema?: Record<string, any>;
  sla?: Record<string, any>;
}

export interface TrustScore {
  server_id: string;
  composite_score: number;
  reliability_score: number;
  security_score: number;
  documentation_score: number;
  responsiveness_score: number;
  confidence: number;
  window: string;
}

export interface PaymentIntent {
  id: string;
  status: string;
  amount: number;
}

export interface Escrow {
  id: string;
  status: string;
  amount: number;
}

export interface CheckoutResult {
  checkout_url: string;
  session_id: string;
  credits: number;
  amount_usd: number;
}

// ---------------------------------------------------------------------------
// Billing responses
// ---------------------------------------------------------------------------

export interface BalanceResponse {
  balance: number;
}

export interface UsageSummaryResponse {
  total_cost: number;
  total_calls: number;
  total_tokens: number;
}

export interface PaymentHistoryResponse {
  history: Record<string, any>[];
}

// ---------------------------------------------------------------------------
// Payment / Escrow responses
// ---------------------------------------------------------------------------

/** Alias for Escrow — used by releaseEscrow, cancelEscrow, createEscrow. */
export interface EscrowResponse {
  id: string;
  status: string;
  amount: number;
}

export interface RefundResponse {
  id: string;
  settlement_id: string;
  amount: number;
  reason?: string;
  status: string;
}

export interface SubscriptionResponse {
  id: string;
  status: string;
  amount: number;
  interval: string;
  next_charge_at: number;
}

export interface SubscriptionDetailResponse {
  id: string;
  payer: string;
  payee: string;
  amount: number;
  interval: string;
  status: string;
  next_charge_at: number;
  charge_count: number;
  created_at: number;
}

export interface SubscriptionListResponse {
  subscriptions: Record<string, any>[];
}

// ---------------------------------------------------------------------------
// Marketplace responses
// ---------------------------------------------------------------------------

export interface ServiceRegistrationResponse {
  id: string;
  name: string;
  status: string;
}

export interface ServiceDetailResponse {
  id: string;
  name: string;
  description: string;
  category: string;
  status: string;
}

export interface ServiceRatingResponse {
  service_id: string;
  agent_id: string;
  rating: number;
}

// ---------------------------------------------------------------------------
// Trust responses
// ---------------------------------------------------------------------------

export interface ServerSearchResult {
  id: string;
  name: string;
  url: string;
}

export interface ServerSearchResponse {
  servers: ServerSearchResult[];
}

// ---------------------------------------------------------------------------
// Identity responses
// ---------------------------------------------------------------------------

export interface AgentIdentityResponse {
  agent_id: string;
  public_key: string;
  created_at: number;
  org_id?: string;
  found: boolean;
}

export interface VerifyAgentResponse {
  valid: boolean;
}

export interface MetricsSubmissionResponse {
  agent_id: string;
  commitment_hashes: string[];
  verified_at: number;
  valid_until: number;
  data_source: string;
  signature: string;
}

export interface VerifiedClaim {
  agent_id: string;
  metric_name: string;
  claim_type: string;
  bound_value: number;
  valid_until: number;
}

export interface VerifiedClaimsResponse {
  claims: VerifiedClaim[];
}

// ---------------------------------------------------------------------------
// Webhook responses
// ---------------------------------------------------------------------------

export interface WebhookResponse {
  id: string;
  agent_id: string;
  url: string;
  event_types: string[];
  filter_agent_ids: string[] | null;
  created_at: number;
  active: boolean;
}

export interface WebhookListResponse {
  webhooks: Record<string, any>[];
}

export interface WebhookDeleteResponse {
  deleted: boolean;
}

// ---------------------------------------------------------------------------
// API key responses
// ---------------------------------------------------------------------------

export interface ApiKeyResponse {
  key: string;
  agent_id: string;
  tier: string;
  created_at: number;
}

export interface KeyRotationResponse {
  new_key: string;
  tier: string;
  agent_id: string;
  revoked: boolean;
}

// ---------------------------------------------------------------------------
// Event responses
// ---------------------------------------------------------------------------

export interface EventPublishResponse {
  event_id: number;
}

export interface EventRecord {
  id: number;
  event_type: string;
  source: string;
  payload: Record<string, any>;
  integrity_hash: string;
  created_at: string;
}

export interface EventListResponse {
  events: EventRecord[];
}

// ---------------------------------------------------------------------------
// Org responses
// ---------------------------------------------------------------------------

export interface OrgResponse {
  org_id: string;
  name: string;
  created_at: number;
}

export interface OrgDetailResponse {
  org_id: string;
  name: string;
  created_at: number;
  members: any[];
}

export interface OrgMemberResponse {
  agent_id: string;
  org_id: string;
}

// ---------------------------------------------------------------------------
// Messaging responses
// ---------------------------------------------------------------------------

export interface NegotiationResponse {
  negotiation_id: string;
  thread_id: string;
  status: string;
  proposed_amount: number;
}

export interface MessageListResponse {
  messages: Record<string, any>[];
}

// ---------------------------------------------------------------------------
// Client options
// ---------------------------------------------------------------------------

export interface A2AClientOptions {
  /** Base URL of the gateway (default: http://localhost:8000). */
  baseUrl?: string;
  /** API key for authenticated endpoints. */
  apiKey?: string;
  /** Request timeout in milliseconds (default: 30000). */
  timeout?: number;
  /** Max retry attempts for transient failures (default: 3). */
  maxRetries?: number;
  /** Base delay between retries in ms (default: 1000). */
  retryBaseDelay?: number;
  /** TTL for pricing cache in ms (default: 300000). */
  pricingCacheTtl?: number;
}
