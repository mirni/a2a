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
async def test_pricing_redirect(client):
    """Old /pricing path redirects to /v1/pricing."""
    resp = await client.get("/pricing", follow_redirects=False)
    assert resp.status_code == 301
    assert "/v1/pricing" in resp.headers["location"]
