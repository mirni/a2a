/** @a2a/sdk — TypeScript SDK for the A2A Commerce Gateway. */

export { A2AClient } from "./client";
export {
  A2AError,
  AuthenticationError,
  InsufficientBalanceError,
  InsufficientTierError,
  ToolNotFoundError,
  RateLimitError,
  ServerError,
} from "./errors";
export type {
  A2AClientOptions,
  CheckoutResult,
  Escrow,
  ExecuteResponse,
  HealthResponse,
  PaymentIntent,
  ToolPricing,
  TrustScore,
} from "./types";
