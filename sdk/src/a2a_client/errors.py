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


class InsufficientTierError(A2AError):
    """403 — tier too low for this tool."""
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


# Map HTTP status codes to exception classes
STATUS_MAP: dict[int, type[A2AError]] = {
    400: ToolNotFoundError,
    401: AuthenticationError,
    402: InsufficientBalanceError,
    403: InsufficientTierError,
    404: ToolNotFoundError,
    429: RateLimitError,
}


def raise_for_status(status: int, body: dict) -> None:
    """Raise the appropriate exception for an error response."""
    error = body.get("error", {})
    message = error.get("message", "Unknown error")
    code = error.get("code", "error")

    exc_class = STATUS_MAP.get(status, ServerError)
    raise exc_class(message=message, code=code, status=status)
