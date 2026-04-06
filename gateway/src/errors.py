"""Error mapping from product exceptions to HTTP JSON responses.

All error responses use RFC 9457 Problem Details format:
  Content-Type: application/problem+json
  Body: {type, title, status, detail, instance}
"""

from __future__ import annotations

import http
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("a2a.errors")

_BASE_URI = "https://api.greenhelix.net/errors"


def _code_to_type_uri(code: str) -> str:
    """Map an error code like 'unknown_tool' to a URI like '.../unknown-tool'."""
    return f"{_BASE_URI}/{code.replace('_', '-')}"


def _title_for_status(status: int) -> str:
    """Return a short human-readable title for an HTTP status code."""
    try:
        return http.HTTPStatus(status).phrase
    except ValueError:
        return "Error"


async def error_response(
    status: int,
    message: str,
    code: str = "error",
    request: Request | None = None,
) -> JSONResponse:
    """Build an RFC 9457 Problem Details error response."""
    body: dict = {
        "type": _code_to_type_uri(code),
        "title": _title_for_status(status),
        "status": status,
        "detail": message,
    }
    if request is not None:
        body["instance"] = request.url.path
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def problem_json_bytes(status: int, code: str, message: str, instance: str = "") -> bytes:
    """Build RFC 9457 Problem Details as bytes for raw ASGI middleware use."""
    import json

    body = {
        "type": _code_to_type_uri(code),
        "title": _title_for_status(status),
        "status": status,
        "detail": message,
    }
    if instance:
        body["instance"] = instance
    return json.dumps(body).encode("utf-8")


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
        "WalletFrozenError": (403, "wallet_frozen"),
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
        "ValueError": (400, "validation_error"),
        # Tool-level errors
        "ToolValidationError": (400, "validation_error"),
        "ToolForbiddenError": (403, "forbidden"),
        "ToolNotFoundError": (404, "not_found"),
        "NegativeCostError": (500, "pricing_error"),
        # Disputes
        "DisputeNotFoundError": (404, "dispute_not_found"),
        "DisputeStateError": (409, "dispute_state_error"),
        # Org/Team
        "OrgNotFoundError": (404, "org_not_found"),
        "MemberNotFoundError": (404, "member_not_found"),
        "LastOwnerError": (400, "last_owner"),
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
    logger.error("Unhandled %s in %s: %s", exc_type, request.url.path, exc, exc_info=exc)
    return await error_response(500, f"Internal error: {exc_type}", "internal_error", request=request)
