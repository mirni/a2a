/** Typed exceptions mapped from HTTP status codes. */

export class A2AError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, code = "error", status = 0) {
    super(message);
    this.name = "A2AError";
    this.code = code;
    this.status = status;
  }
}

export class AuthenticationError extends A2AError {
  constructor(message: string, code = "invalid_key") {
    super(message, code, 401);
    this.name = "AuthenticationError";
  }
}

export class InsufficientBalanceError extends A2AError {
  constructor(message: string, code = "insufficient_balance") {
    super(message, code, 402);
    this.name = "InsufficientBalanceError";
  }
}

export class InsufficientTierError extends A2AError {
  constructor(message: string, code = "insufficient_tier") {
    super(message, code, 403);
    this.name = "InsufficientTierError";
  }
}

export class ToolNotFoundError extends A2AError {
  constructor(message: string, code = "unknown_tool") {
    super(message, code, 404);
    this.name = "ToolNotFoundError";
  }
}

export class RateLimitError extends A2AError {
  constructor(message: string, code = "rate_limit_exceeded") {
    super(message, code, 429);
    this.name = "RateLimitError";
  }
}

export class ServerError extends A2AError {
  constructor(message: string, code = "internal_error", status = 500) {
    super(message, code, status);
    this.name = "ServerError";
  }
}

/** Status codes that are safe to retry. */
export const RETRYABLE_STATUS_CODES = new Set([429, 500, 502, 503, 504]);

const STATUS_MAP: Record<number, new (m: string, c: string) => A2AError> = {
  400: ToolNotFoundError,
  401: AuthenticationError,
  402: InsufficientBalanceError,
  403: InsufficientTierError,
  404: ToolNotFoundError,
  429: RateLimitError,
};

/** Throw the appropriate error for an HTTP error response. */
export function raiseForStatus(status: number, body: Record<string, any>): never {
  const error = body.error ?? {};
  const message: string = error.message ?? "Unknown error";
  const code: string = error.code ?? "error";

  const ErrorClass = STATUS_MAP[status] ?? ServerError;
  throw new ErrorClass(message, code);
}
