"""Tests for converting /v1/pricing catalog entries to MCP Tool objects."""

from __future__ import annotations

from a2a_mcp_server.tool_discovery import catalog_to_mcp_tools


def test_catalog_to_mcp_tools_preserves_name_and_description():
    catalog = [
        {
            "name": "get_balance",
            "service": "billing",
            "description": "Get wallet balance for an agent.",
            "input_schema": {
                "type": "object",
                "properties": {"agent_id": {"type": "string"}},
                "required": ["agent_id"],
            },
            "pricing": {"per_call": 0.0},
            "tier_required": "free",
        }
    ]
    tools = catalog_to_mcp_tools(catalog)
    assert len(tools) == 1
    assert tools[0].name == "get_balance"
    assert "balance" in tools[0].description.lower()
    assert tools[0].inputSchema["properties"] == {"agent_id": {"type": "string"}}


def test_catalog_to_mcp_tools_injects_pricing_and_tier_into_description():
    """Pricing + tier metadata should be visible to planner LLMs via description."""
    catalog = [
        {
            "name": "create_intent",
            "service": "payments",
            "description": "Create a payment intent.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "pricing": {"per_call": 0.5},
            "tier_required": "pro",
        }
    ]
    tools = catalog_to_mcp_tools(catalog)
    desc = tools[0].description
    assert "0.5" in desc or "0.50" in desc
    assert "pro" in desc.lower()


def test_catalog_to_mcp_tools_accepts_missing_fields():
    """Minimal catalog entry should still produce a usable Tool."""
    catalog = [
        {
            "name": "ping",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
    ]
    tools = catalog_to_mcp_tools(catalog)
    assert len(tools) == 1
    assert tools[0].name == "ping"


def test_catalog_to_mcp_tools_skips_entries_without_name():
    catalog = [
        {"description": "nameless", "input_schema": {}},
        {"name": "valid", "input_schema": {"type": "object"}},
    ]
    tools = catalog_to_mcp_tools(catalog)
    assert len(tools) == 1
    assert tools[0].name == "valid"
