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


# Keys that must never appear in audit logs
_SENSITIVE_KEYS = frozenset({
    "api_key", "secret", "password", "token", "authorization",
    "secret_key", "private_key", "access_token", "refresh_token",
    "credit_card", "card_number", "cvv", "ssn",
})


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    """Remove sensitive values from parameters before logging."""
    sanitized = {}
    for key, value in params.items():
        if key.lower() in _SENSITIVE_KEYS:
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
