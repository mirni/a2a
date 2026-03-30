"""Error mapping from product exceptions to HTTP JSON responses."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse


async def error_response(
    status: int,
    message: str,
    code: str = "error",
    request: Request | None = None,
) -> JSONResponse:
    """Build a standard error JSON response with optional request_id."""
    body: dict = {"success": False, "error": {"code": code, "message": message}}
    if request is not None:
        request_id = getattr(request.state, "correlation_id", None) or ""
        body["request_id"] = request_id
    return JSONResponse(body, status_code=status)


async def handle_product_exception(request: Request, exc: Exception) -> JSONResponse:
    """Map known product exceptions to HTTP status codes."""
    exc_type = type(exc).__name__
    msg = str(exc)

    mapping: dict[str, tuple[int, str]] = {
        # Paywall / Auth
        "InvalidKeyError": (401, "invalid_key"),
        "ExpiredKeyError": (401, "expired_key"),
        "PaywallAuthError": (401, "authentication_error"),
        # Scoping
        "KeyScopeError": (403, "scope_violation"),
        # Tier
        "TierInsufficientError": (403, "insufficient_tier"),
        # Rate limits
        "RateLimitError": (429, "rate_limit_exceeded"),
        "RateLimitExceededError": (429, "rate_limit_exceeded"),
        "SpendCapExceededError": (429, "spend_cap_exceeded"),
        # Balance
        "InsufficientCreditsError": (402, "insufficient_balance"),
        "InsufficientBalanceError": (402, "insufficient_balance"),
        # Not found
        "ServiceNotFoundError": (404, "service_not_found"),
        "ServerNotFoundError": (404, "server_not_found"),
        "IntentNotFoundError": (404, "intent_not_found"),
        "EscrowNotFoundError": (404, "escrow_not_found"),
        "WalletNotFoundError": (404, "wallet_not_found"),
        "SubscriptionNotFoundError": (404, "subscription_not_found"),
        "AgentNotFoundError": (404, "agent_not_found"),
        # Conflict / invalid state
        "InvalidStateError": (409, "invalid_state"),
        "DuplicateIntentError": (409, "duplicate_intent"),
        "DuplicateServiceError": (409, "duplicate_service"),
        "AgentAlreadyExistsError": (409, "agent_already_exists"),
        # Validation
        "ValidationError": (400, "validation_error"),
        "InvalidMetricError": (400, "invalid_metric"),
        # "ValueError" removed — use ToolValidationError for tool input errors
        # Tool-level errors
        "ToolValidationError": (400, "validation_error"),
        "ToolNotFoundError": (404, "not_found"),
        "NegativeCostError": (500, "pricing_error"),
        # Disputes
        "DisputeNotFoundError": (404, "dispute_not_found"),
        "DisputeStateError": (409, "dispute_state_error"),
        "SubscriptionStateError": (409, "invalid_state"),
        # Payment engine base error
        "PaymentError": (400, "payment_error"),
        # x402 protocol
        "X402VerificationError": (402, "payment_verification_failed"),
        "X402ReplayError": (402, "payment_replay_detected"),
    }

    if exc_type in mapping:
        status, code = mapping[exc_type]
        return await error_response(status, msg, code, request=request)

    # Unknown → 500
    return await error_response(500, f"Internal error: {exc_type}", "internal_error", request=request)
