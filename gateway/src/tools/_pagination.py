"""Pagination helper for list/search tool functions.

When ``paginate=true`` is passed in params, wraps results in a standard
paginated envelope: ``{items, total, offset, limit, has_more}``.

Supports both offset-based and cursor-based pagination.
"""

from __future__ import annotations

import base64
from typing import Any


def encode_cursor(offset: int) -> str:
    """Encode an offset into an opaque cursor string."""
    return base64.urlsafe_b64encode(f"off:{offset}".encode()).decode()


def decode_cursor(cursor: str) -> int:
    """Decode an opaque cursor string back to an offset."""
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        if decoded.startswith("off:"):
            return max(0, int(decoded[4:]))
    except Exception:
        pass
    return 0


def _paginate(
    items: list[Any],
    params: dict[str, Any],
    *,
    total_override: int | None = None,
) -> dict[str, Any]:
    """Slice *items* according to offset/limit and return pagination metadata.

    Parameters
    ----------
    items:
        The full (or pre-counted) list of result dicts.
    params:
        The tool params dict; reads ``offset``, ``limit``, and ``cursor``.
    total_override:
        If provided, use this as the total count instead of ``len(items)``.
        Useful when items are already sliced by the storage layer.
    """
    # Cursor takes precedence over offset
    cursor = params.get("cursor")
    if cursor:
        offset = decode_cursor(cursor)
    else:
        offset = max(0, int(params.get("offset", 0)))

    limit = max(0, int(params.get("limit", 50)))
    total = total_override if total_override is not None else len(items)

    # If items were fetched in full (no storage-level pagination), slice here
    if total_override is None:
        page = items[offset : offset + limit] if limit > 0 else []
    else:
        page = items

    has_more = (offset + limit) < total
    result = {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
    }

    if has_more:
        result["next_cursor"] = encode_cursor(offset + limit)

    return result
