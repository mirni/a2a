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
