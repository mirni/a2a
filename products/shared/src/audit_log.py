"""Structured audit logging for all connector operations."""

import json
import logging
import time
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("a2a.audit")

# Context var to track request correlation
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def set_request_id(rid: str) -> None:
    """Set the current request ID for correlation."""
    _request_id.set(rid)


def get_request_id() -> str | None:
    """Get the current request ID."""
    return _request_id.get()


class AuditEntry:
    """A single audit log entry."""

    def __init__(
        self,
        operation: str,
        connector: str,
        params: dict[str, Any] | None = None,
        result_summary: str | None = None,
        error: str | None = None,
        duration_ms: float | None = None,
    ):
        self.timestamp = time.time()
        self.operation = operation
        self.connector = connector
        self.request_id = get_request_id()
        self.params = _sanitize_params(params or {})
        self.result_summary = result_summary
        self.error = error
        self.duration_ms = duration_ms

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": self.timestamp,
            "op": self.operation,
            "connector": self.connector,
        }
        if self.request_id:
            entry["request_id"] = self.request_id
        if self.params:
            entry["params"] = self.params
        if self.result_summary:
            entry["result"] = self.result_summary
        if self.error:
            entry["error"] = self.error
        if self.duration_ms is not None:
            entry["duration_ms"] = round(self.duration_ms, 2)
        return entry


# Substrings that indicate a key is sensitive (case-insensitive matching).
# A key is redacted if ANY of these appear as a substring in the lowered key.
_SENSITIVE_SUBSTRINGS = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "authorization",
    "private_key",
    "credit_card",
    "card_number",
    "cvv",
    "ssn",
)


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name contains any sensitive substring."""
    lower = key.lower()
    return any(sub in lower for sub in _SENSITIVE_SUBSTRINGS)


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive values from parameters before logging."""
    sanitized: dict[str, Any] = {}
    for key, value in params.items():
        if _is_sensitive_key(key):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, dict):
            sanitized[key] = _sanitize_params(value)
        else:
            sanitized[key] = value
    return sanitized


def log_operation(
    operation: str,
    connector: str,
    params: dict[str, Any] | None = None,
    result_summary: str | None = None,
    error: str | None = None,
    duration_ms: float | None = None,
) -> AuditEntry:
    """Log an operation to the audit trail.

    Returns the AuditEntry for testing/inspection.
    """
    entry = AuditEntry(
        operation=operation,
        connector=connector,
        params=params,
        result_summary=result_summary,
        error=error,
        duration_ms=duration_ms,
    )

    log_line = json.dumps(entry.to_dict(), default=str)
    if error:
        logger.error(log_line)
    else:
        logger.info(log_line)

    return entry
