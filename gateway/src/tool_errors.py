"""Tool-level exception types for structured error handling.

These exceptions are raised by tool functions instead of returning error dicts,
and are mapped to appropriate HTTP status codes in the error handler.
"""

from __future__ import annotations


class ToolValidationError(ValueError):
    """Raised when a tool receives invalid input (maps to 400)."""


class ToolForbiddenError(PermissionError):
    """Raised when a tool call is forbidden due to ownership/auth (maps to 403)."""


class ToolNotFoundError(LookupError):
    """Raised when a tool cannot find a requested resource (maps to 404)."""


class NegativeCostError(ValueError):
    """Raised when cost calculation produces a negative value (maps to 500)."""


class X402VerificationError(Exception):
    """Raised when x402 payment proof fails verification (maps to 402)."""


class X402ReplayError(X402VerificationError):
    """Raised when x402 payment nonce has already been used (maps to 402)."""
