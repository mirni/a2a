"""Convert A2A gateway catalog entries into ``mcp.types.Tool`` objects.

The gateway serves tool metadata via ``GET /v1/pricing`` as::

    {
        "name":          "create_intent",
        "service":       "payments",
        "description":   "Create a payment intent...",
        "input_schema":  { JSON Schema },
        "output_schema": { JSON Schema },
        "pricing":       {"per_call": 0.5},
        "sla":           {"max_latency_ms": 200},
        "tier_required": "pro"
    }

MCP clients only see ``name`` / ``description`` / ``inputSchema``, so we
fold pricing and tier hints into the description. That gives planner
LLMs (Claude, GPT-5, Gemini, ...) the context to pick the cheapest or
lowest-tier tool for a given job — an Agent-SEO optimisation.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool


def catalog_to_mcp_tools(catalog: list[dict[str, Any]]) -> list[Tool]:
    """Convert ``/v1/pricing`` entries into MCP ``Tool`` objects."""
    tools: list[Tool] = []
    for entry in catalog:
        name = entry.get("name")
        if not name:
            continue
        description = _build_description(entry)
        input_schema = entry.get("input_schema") or {"type": "object", "properties": {}}
        output_schema = entry.get("output_schema")
        kwargs: dict[str, Any] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        if isinstance(output_schema, dict) and output_schema:
            kwargs["outputSchema"] = output_schema
        tools.append(Tool(**kwargs))
    return tools


def _build_description(entry: dict[str, Any]) -> str:
    base = (entry.get("description") or "").strip()
    service = entry.get("service")
    pricing = entry.get("pricing") or {}
    tier = entry.get("tier_required") or "free"
    per_call = pricing.get("per_call")

    extras: list[str] = []
    if service:
        extras.append(f"service={service}")
    if per_call is not None:
        # Format 0.0 as "0" and 0.5 as "0.5" — human-friendly, deterministic
        if isinstance(per_call, (int, float)):
            if float(per_call) == 0:
                extras.append("cost=0 credits")
            else:
                extras.append(f"cost={per_call} credits/call")
    extras.append(f"tier={tier}")

    suffix = " [" + ", ".join(extras) + "]"
    if base:
        return base + suffix
    return f"A2A gateway tool{suffix}"
