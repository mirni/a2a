"""Tests for GET /v1/health and HealthMonitor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from gateway.src._version import __version__
from gateway.src.health_monitor import HealthMonitor


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == __version__
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


# ---------------------------------------------------------------------------
# HealthMonitor unit tests
# ---------------------------------------------------------------------------


def _make_service(svc_id: str, provider_id: str, endpoint: str | None = None):
    svc = MagicMock()
    svc.id = svc_id
    svc.provider_id = provider_id
    svc.endpoint = endpoint
    return svc


@pytest.mark.asyncio
async def test_health_monitor_empty_services():
    """Empty service list -> no errors."""
    marketplace = AsyncMock()
    marketplace.search.return_value = []
    event_bus = AsyncMock()
    monitor = HealthMonitor(marketplace, event_bus)

    await monitor.check_services()

    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_monitor_skips_services_without_endpoint():
    """Services without endpoint are skipped."""
    marketplace = AsyncMock()
    marketplace.search.return_value = [_make_service("svc-1", "provider-1", None)]
    event_bus = AsyncMock()
    monitor = HealthMonitor(marketplace, event_bus)

    await monitor.check_services()

    event_bus.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_health_monitor_timeout_publishes_event():
    """Timeout -> publishes trust.health_check_failed event."""
    marketplace = AsyncMock()
    marketplace.search.return_value = [_make_service("svc-1", "provider-1", "https://example.com")]
    event_bus = AsyncMock()
    monitor = HealthMonitor(marketplace, event_bus)

    with patch("gateway.src.health_monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await monitor.check_services()

    event_bus.publish.assert_awaited_once()
    call_args = event_bus.publish.call_args
    assert call_args[0][0] == "trust.health_check_failed"
    assert call_args[1]["payload"]["server_id"] == "provider-1"
    assert call_args[1]["payload"]["penalty"] == 20.0


@pytest.mark.asyncio
async def test_health_monitor_connect_error_publishes_event():
    """ConnectError -> publishes trust.health_check_failed event."""
    marketplace = AsyncMock()
    marketplace.search.return_value = [_make_service("svc-1", "provider-1", "https://example.com")]
    event_bus = AsyncMock()
    monitor = HealthMonitor(marketplace, event_bus)

    with patch("gateway.src.health_monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await monitor.check_services()

    event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_monitor_5xx_publishes_event():
    """5xx response -> publishes trust.health_check_failed event."""
    marketplace = AsyncMock()
    marketplace.search.return_value = [_make_service("svc-1", "provider-1", "https://example.com")]
    event_bus = AsyncMock()
    monitor = HealthMonitor(marketplace, event_bus)

    with patch("gateway.src.health_monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 503
        mock_response.request = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await monitor.check_services()

    event_bus.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_monitor_2xx_no_event():
    """200 response -> no event published."""
    marketplace = AsyncMock()
    marketplace.search.return_value = [_make_service("svc-1", "provider-1", "https://example.com")]
    event_bus = AsyncMock()
    monitor = HealthMonitor(marketplace, event_bus)

    with patch("gateway.src.health_monitor.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await monitor.check_services()

    event_bus.publish.assert_not_awaited()


# ---------------------------------------------------------------------------
# Agent card tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_card_returns_valid_json(client):
    """/.well-known/agent-card.json must return valid agent card."""
    resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    assert data["name"] == "A2A Commerce Gateway"
    assert "url" in data
    assert "version" in data
    assert "capabilities" in data
    assert "skills" in data
    assert isinstance(data["skills"], list)
    assert len(data["skills"]) > 0


@pytest.mark.asyncio
async def test_agent_card_no_auth_required(client):
    """Agent card must be accessible without authentication."""
    resp = await client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_agent_card_skills_have_required_fields(client):
    """Each skill in the agent card must have id, name, and description."""
    resp = await client.get("/.well-known/agent-card.json")
    data = resp.json()
    for skill in data["skills"]:
        assert "id" in skill, f"Skill missing 'id': {skill}"
        assert "name" in skill, f"Skill missing 'name': {skill}"
        assert "description" in skill, f"Skill missing 'description': {skill}"


@pytest.mark.asyncio
async def test_agent_card_includes_auth_info(client):
    """Agent card must describe authentication requirements."""
    resp = await client.get("/.well-known/agent-card.json")
    data = resp.json()
    assert "authentication" in data
    assert data["authentication"]["schemes"] is not None
