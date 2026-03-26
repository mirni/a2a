"""Structured error types for all connectors."""

from typing import Any


class ConnectorError(Exception):
    """Base error for all connector operations.

    Provides machine-readable error codes and structured details
    that agents can parse and act on.
    """

    def __init__(
        self,
        message: str,
        code: str,
        details: dict[str, Any] | None = None,
        retryable: bool = False,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        self.retryable = retryable
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": True,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class ValidationError(ConnectorError):
    """Input validation failed."""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="VALIDATION_ERROR", details=details, retryable=False)


class AuthenticationError(ConnectorError):
    """Authentication failed (bad API key, expired token, etc)."""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, code="AUTH_ERROR", retryable=False)


class RateLimitError(ConnectorError):
    """Upstream rate limit hit."""

    def __init__(self, retry_after: float | None = None):
        details = {"retry_after": retry_after} if retry_after else {}
        super().__init__(
            "Rate limit exceeded", code="RATE_LIMIT", details=details, retryable=True
        )


class UpstreamError(ConnectorError):
    """Upstream service returned an error."""

    def __init__(self, message: str, status_code: int | None = None, retryable: bool = False):
        details: dict[str, Any] = {}
        if status_code:
            details["status_code"] = status_code
        super().__init__(message, code="UPSTREAM_ERROR", details=details, retryable=retryable)


class TimeoutError(ConnectorError):
    """Operation timed out."""

    def __init__(self, message: str = "Operation timed out"):
        super().__init__(message, code="TIMEOUT", retryable=True)
