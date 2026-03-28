"""Tool-level exception types for structured error handling.

These exceptions are raised by tool functions instead of returning error dicts,
and are mapped to appropriate HTTP status codes in the error handler.
"""

from __future__ import annotations


class ToolValidationError(ValueError):
    """Raised when a tool receives invalid input (maps to 400)."""


class ToolNotFoundError(LookupError):
    """Raised when a tool cannot find a requested resource (maps to 404)."""


class NegativeCostError(ValueError):
    """Raised when cost calculation produces a negative value (maps to 500)."""
