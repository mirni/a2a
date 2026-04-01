"""Response serialization: monetary values as strings, timestamps as ISO 8601.

Applied to execute.py responses before sending to clients.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

# Fields that contain monetary values (should be serialized as "123.45" strings)
_MONETARY_FIELDS: frozenset[str] = frozenset(
    {
        "balance",
        "amount",
        "cost",
        "fee",
        "new_balance",
        "price",
        "charged",
        "total",
        "min_fee",
        "max_fee",
        "per_call",
        "refund_amount",
        "original_amount",
        "net_amount",
        "remaining",
        "spent",
        "cap",
        "used",
        "from_amount",
        "to_amount",
        "rate",
        "average_rating",
        "discount_percent",
        "original_price",
        "discounted_price",
    }
)

# Fields that contain Unix timestamps (should be serialized as ISO 8601)
_TIMESTAMP_FIELDS: frozenset[str] = frozenset(
    {
        "created_at",
        "updated_at",
        "captured_at",
        "settled_at",
        "expires_at",
        "expired_at",
        "cancelled_at",
        "refunded_at",
        "released_at",
        "resolved_at",
        "suspended_at",
        "reactivated_at",
        "registered_at",
        "verified_at",
        "last_seen",
        "timestamp",
        "revoked_at",
        "restored_at",
    }
)


def serialize_money(value: Any) -> str:
    """Format a numeric value as a 2-decimal fixed-point string.

    Uses Decimal internally to avoid float precision loss (e.g. 0.1+0.2).
    """
    if isinstance(value, str):
        return value
    return f"{Decimal(str(value)):.2f}"


def serialize_timestamp(value: Any) -> str:
    """Convert a Unix timestamp (float/int) to ISO 8601 UTC string."""
    if isinstance(value, str):
        # Already a string — check if it looks like ISO 8601
        if "T" in value or "-" in value:
            return value
        # It's a numeric string — convert
        try:
            ts = float(value)
        except (ValueError, TypeError):
            return value
    elif isinstance(value, (int, float)):
        ts = float(value)
    else:
        return str(value)
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


def serialize_response(data: Any) -> Any:
    """Walk a response dict/list and convert monetary/timestamp fields."""
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key in _MONETARY_FIELDS and isinstance(value, (int, float)):
                result[key] = serialize_money(value)
            elif key in _TIMESTAMP_FIELDS and value is not None:
                result[key] = serialize_timestamp(value)
            else:
                result[key] = serialize_response(value)
        return result
    if isinstance(data, list):
        return [serialize_response(item) for item in data]
    return data
