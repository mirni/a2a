"""Tests for GET /v1/health."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert isinstance(data["tools"], int)
    assert data["tools"] > 0


@pytest.mark.asyncio
async def test_health_method_not_allowed(client):
    resp = await client.post("/v1/health")
    assert resp.status_code == 405


@pytest.mark.asyncio
async def test_health_redirect(client):
    """Old /health path redirects to /v1/health."""
    resp = await client.get("/health", follow_redirects=False)
    assert resp.status_code == 301
    assert "/v1/health" in resp.headers["location"]
