"""Typed exceptions mapped from HTTP status codes."""

from __future__ import annotations


class A2AError(Exception):
    """Base error for all A2A SDK errors."""

    def __init__(self, message: str, code: str = "error", status: int = 0) -> None:
        self.message = message
        self.code = code
        self.status = status
        super().__init__(message)


class AuthenticationError(A2AError):
    """401 — invalid or missing API key."""

    pass


class InsufficientBalanceError(A2AError):
    """402 — not enough credits."""

    pass


class PermissionDeniedError(A2AError):
    """403 — forbidden / permission denied."""

    pass


class InsufficientTierError(PermissionDeniedError):
    """403 — tier too low for this tool (subclass of PermissionDeniedError)."""

    pass


class ToolNotFoundError(A2AError):
    """400/404 — unknown tool name."""

    pass


class RateLimitError(A2AError):
    """429 — rate limit exceeded."""

    pass


class ServerError(A2AError):
    """5xx — gateway internal error."""

    pass


class RetryableError(A2AError):
    """Error that can be retried (429, 5xx)."""

    pass


# Map HTTP status codes to exception classes
STATUS_MAP: dict[int, type[A2AError]] = {
    400: ToolNotFoundError,
    401: AuthenticationError,
    402: InsufficientBalanceError,
    403: PermissionDeniedError,
    404: ToolNotFoundError,
    429: RateLimitError,
}

# Status codes that are safe to retry
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


def raise_for_status(status: int, body: dict) -> None:
    """Raise the appropriate exception for an error response.

    Supports both legacy execute format ``{"error": {"message", "code"}}``
    and RFC 9457 format ``{"type", "title", "status", "detail"}``.
    """
    # RFC 9457 format (REST endpoints)
    if "detail" in body and "type" in body:
        message = body.get("detail", "Unknown error")
        # Extract error code from type URL: .../errors/<code>
        type_url = body.get("type", "")
        code = type_url.rsplit("/", 1)[-1] if "/" in type_url else "error"
    else:
        # Legacy execute format
        error = body.get("error", {})
        message = error.get("message", body.get("detail", "Unknown error"))
        code = error.get("code", "error")

    exc_class = STATUS_MAP.get(status, ServerError)
    # Distinguish tier-specific 403 from generic permission denied
    if status == 403 and "tier" in code:
        exc_class = InsufficientTierError
    raise exc_class(message=message, code=code, status=status)
