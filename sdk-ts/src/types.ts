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
