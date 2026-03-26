"""Tests for GET /health."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"
    assert isinstance(data["tools"], int)
    assert data["tools"] > 0


@pytest.mark.asyncio
async def test_health_method_not_allowed(client):
    resp = await client.post("/health")
    assert resp.status_code == 405
