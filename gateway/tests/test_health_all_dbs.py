"""Tests for extended /v1/health endpoint that probes ALL product databases."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_health_returns_all_db_statuses(client):
    """Health check must return a per-database status breakdown."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()

    # Top-level fields must still exist (backward compat)
    assert data["status"] == "ok"
    assert "version" in data
    assert "tools" in data

    # Must include a "databases" dict with per-db status
    assert "databases" in data
    databases = data["databases"]
    assert isinstance(databases, dict)

    expected_dbs = {
        "billing",
        "paywall",
        "payments",
        "marketplace",
        "trust",
        "identity",
        "event_bus",
        "webhooks",
        "messaging",
        "disputes",
    }
    assert set(databases.keys()) == expected_dbs

    # When healthy, every DB should report "ok"
    for db_name, db_status in databases.items():
        assert db_status == "ok", f"Expected DB '{db_name}' to be 'ok', got '{db_status}'"


@pytest.mark.asyncio
async def test_health_backward_compat_db_field(client):
    """The legacy 'db' field must still be present and 'ok' when all DBs are healthy."""
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["db"] == "ok"


@pytest.mark.asyncio
async def test_health_degraded_when_one_db_fails(client, app):
    """When a single DB probe fails, status should be 'degraded', HTTP 503,
    and that DB should show 'error' in the breakdown while others show 'ok'."""
    ctx = app.state.ctx

    # Save original and inject a failing mock for paywall DB
    original_db = ctx.paywall_storage._db
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("paywall DB down"))
    ctx.paywall_storage._db = mock_db

    try:
        resp = await client.get("/v1/health")
        assert resp.status_code == 503
        data = resp.json()

        assert data["status"] == "degraded"
        assert data["databases"]["paywall"] == "error"

        # Other databases should still be ok
        for db_name, db_status in data["databases"].items():
            if db_name != "paywall":
                assert db_status == "ok", f"DB '{db_name}' should be 'ok', got '{db_status}'"
    finally:
        ctx.paywall_storage._db = original_db


@pytest.mark.asyncio
async def test_health_degraded_when_billing_db_fails(client, app):
    """When billing DB fails, the legacy 'db' field should also show 'error'."""
    ctx = app.state.ctx

    original_db = ctx.tracker.storage._db
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("billing DB down"))
    ctx.tracker.storage._db = mock_db

    try:
        resp = await client.get("/v1/health")
        assert resp.status_code == 503
        data = resp.json()

        assert data["status"] == "degraded"
        assert data["db"] == "error"
        assert data["databases"]["billing"] == "error"
    finally:
        ctx.tracker.storage._db = original_db


@pytest.mark.asyncio
async def test_health_degraded_multiple_dbs_fail(client, app):
    """When multiple DBs fail, all should show 'error' and status is 'degraded'."""
    ctx = app.state.ctx

    # Save originals
    orig_billing = ctx.tracker.storage._db
    orig_trust = ctx.trust_api.storage._db

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=Exception("DB down"))
    ctx.tracker.storage._db = mock_db
    ctx.trust_api.storage._db = mock_db

    try:
        resp = await client.get("/v1/health")
        assert resp.status_code == 503
        data = resp.json()

        assert data["status"] == "degraded"
        assert data["databases"]["billing"] == "error"
        assert data["databases"]["trust"] == "error"

        # Others should be ok
        for db_name in (
            "paywall",
            "payments",
            "marketplace",
            "identity",
            "event_bus",
            "webhooks",
            "messaging",
            "disputes",
        ):
            assert data["databases"][db_name] == "ok"
    finally:
        ctx.tracker.storage._db = orig_billing
        ctx.trust_api.storage._db = orig_trust
