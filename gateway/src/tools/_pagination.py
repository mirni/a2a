"""Pagination helper for list/search tool functions.

When ``paginate=true`` is passed in params, wraps results in a standard
paginated envelope: ``{items, total, offset, limit, has_more}``.
"""

from __future__ import annotations

from typing import Any


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
        The tool params dict; reads ``offset`` and ``limit``.
    total_override:
        If provided, use this as the total count instead of ``len(items)``.
        Useful when items are already sliced by the storage layer.
    """
    offset = max(0, int(params.get("offset", 0)))
    limit = max(0, int(params.get("limit", 50)))
    total = total_override if total_override is not None else len(items)

    # If items were fetched in full (no storage-level pagination), slice here
    if total_override is None:
        page = items[offset : offset + limit] if limit > 0 else []
    else:
        page = items

    return {
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": (offset + limit) < total,
    }
