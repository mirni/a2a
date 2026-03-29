"""Tests for GET /v1/pricing and GET /v1/pricing/{tool}."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_pricing_list(client):
    resp = await client.get("/v1/pricing")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    assert len(data["tools"]) > 0
    # Each tool should have required fields
    tool = data["tools"][0]
    assert "name" in tool
    assert "service" in tool
    assert "pricing" in tool


@pytest.mark.asyncio
async def test_pricing_detail_found(client):
    resp = await client.get("/v1/pricing/get_balance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool"]["name"] == "get_balance"
    assert data["tool"]["service"] == "billing"


@pytest.mark.asyncio
async def test_pricing_detail_not_found(client):
    resp = await client.get("/v1/pricing/nonexistent_tool")
    assert resp.status_code == 404
    data = resp.json()
    assert data["success"] is False
    assert data["error"]["code"] == "tool_not_found"


@pytest.mark.asyncio
async def test_pricing_detail_percentage_model(client):
    """Payment tools with percentage-based pricing should return percentage fields."""
    resp = await client.get("/v1/pricing/create_intent")
    assert resp.status_code == 200
    data = resp.json()
    pricing = data["tool"]["pricing"]
    assert pricing["model"] == "percentage"
    assert pricing["percentage"] == 2.0
    assert pricing["min_fee"] == 0.01
    assert pricing["max_fee"] == 5.0


@pytest.mark.asyncio
async def test_pricing_detail_escrow_percentage(client):
    """Escrow tool should have percentage-based pricing."""
    resp = await client.get("/v1/pricing/create_escrow")
    assert resp.status_code == 200
    data = resp.json()
    pricing = data["tool"]["pricing"]
    assert pricing["model"] == "percentage"
    assert pricing["percentage"] == 1.5
    assert pricing["min_fee"] == 0.01
    assert pricing["max_fee"] == 10.0


@pytest.mark.asyncio
async def test_pricing_detail_flat_model(client):
    """Non-payment tools should still use flat per_call pricing."""
    resp = await client.get("/v1/pricing/get_balance")
    assert resp.status_code == 200
    data = resp.json()
    pricing = data["tool"]["pricing"]
    assert "per_call" in pricing
    assert pricing["per_call"] == 0.0


@pytest.mark.asyncio
async def test_pricing_redirect(client):
    """Old /pricing path redirects to /v1/pricing."""
    resp = await client.get("/pricing", follow_redirects=False)
    assert resp.status_code == 301
    assert "/v1/pricing" in resp.headers["location"]


# ---------------------------------------------------------------------------
# Pagination (I-3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pricing_list_with_limit(client):
    """?limit=3 should return at most 3 tools."""
    resp = await client.get("/v1/pricing?limit=3")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tools"]) == 3
    assert data["total"] > 3  # catalog has >3 tools
    assert data["limit"] == 3
    assert data["offset"] == 0


@pytest.mark.asyncio
async def test_pricing_list_with_offset(client):
    """?offset=2 should skip the first 2 tools."""
    resp_all = await client.get("/v1/pricing")
    all_tools = resp_all.json()["tools"]

    resp = await client.get("/v1/pricing?offset=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["offset"] == 2
    # First tool in paginated response should be the 3rd tool from full list
    assert data["tools"][0]["name"] == all_tools[2]["name"]


@pytest.mark.asyncio
async def test_pricing_list_with_limit_and_offset(client):
    """?limit=2&offset=1 should return tools[1:3]."""
    resp_all = await client.get("/v1/pricing")
    all_tools = resp_all.json()["tools"]

    resp = await client.get("/v1/pricing?limit=2&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tools"]) == 2
    assert data["tools"][0]["name"] == all_tools[1]["name"]
    assert data["tools"][1]["name"] == all_tools[2]["name"]


@pytest.mark.asyncio
async def test_pricing_list_offset_beyond_catalog(client):
    """?offset beyond catalog length should return empty list."""
    resp = await client.get("/v1/pricing?offset=9999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tools"] == []
    assert data["total"] > 0


@pytest.mark.asyncio
async def test_pricing_list_negative_limit_ignored(client):
    """Negative limit should be treated as no limit (all tools returned)."""
    resp = await client.get("/v1/pricing?limit=-1")
    assert resp.status_code == 200
    data = resp.json()
    # Should return all tools (negative limit ignored)
    assert len(data["tools"]) == data["total"]


# ---------------------------------------------------------------------------
# Pricing summary (AD-6 / U-3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pricing_summary(client):
    """GET /v1/pricing/summary should return pricing grouped by service."""
    resp = await client.get("/v1/pricing/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "services" in data
    assert isinstance(data["services"], list)
    assert len(data["services"]) > 0

    svc = data["services"][0]
    assert "service" in svc
    assert "tool_count" in svc
    assert "tools" in svc
    assert isinstance(svc["tools"], list)
    assert len(svc["tools"]) > 0

    # Each tool in summary should have name and pricing
    tool = svc["tools"][0]
    assert "name" in tool
    assert "pricing" in tool
