"""Service catalog loader.

Loads tool definitions from catalog.json and provides lookup helpers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CATALOG: list[dict[str, Any]] | None = None


def _load() -> list[dict[str, Any]]:
    global _CATALOG
    if _CATALOG is None:
        path = Path(__file__).parent / "catalog.json"
        with open(path) as f:
            _CATALOG = json.load(f)
    return _CATALOG


def get_catalog() -> list[dict[str, Any]]:
    """Return the full tool catalog."""
    return list(_load())


def get_tool(name: str) -> dict[str, Any] | None:
    """Look up a single tool by name. Returns None if not found."""
    for tool in _load():
        if tool["name"] == name:
            return dict(tool)
    return None


def get_tools_by_service(service: str) -> list[dict[str, Any]]:
    """Return all tools belonging to a given service (billing, payments, etc.)."""
    return [dict(t) for t in _load() if t["service"] == service]


def tool_count() -> int:
    """Return the number of tools in the catalog."""
    return len(_load())


def reset() -> None:
    """Reset cached catalog (useful for testing)."""
    global _CATALOG
    _CATALOG = None
