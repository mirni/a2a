"""Tests for GET /v1/health."""

from __future__ import annotations

from unittest.mock import AsyncMock

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


@pytest.mark.asyncio
async def test_health_includes_db_ok(client):
    """Health check must probe the DB and return db status."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"] == "ok"


@pytest.mark.asyncio
async def test_health_returns_degraded_when_db_fails(client, app):
    """When DB probe fails, status should be 'degraded' and db should be 'error'."""
    ctx = app.state.ctx
    original_db = ctx.tracker.storage._db

    # Replace the internal _db with a mock that raises on execute
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("DB connection lost"))
    ctx.tracker.storage._db = mock_db

    try:
        resp = await client.get("/v1/health")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["db"] == "error"
    finally:
        ctx.tracker.storage._db = original_db
