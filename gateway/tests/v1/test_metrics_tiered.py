"""F3 audit v1.4.4: Tier-gated /v1/metrics access.

Enterprise+ tier can access metrics from any IP.
Localhost/internal IPs still bypass auth for monitoring infra.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def enterprise_api_key(app, client):
    """Create an enterprise-tier API key with a funded wallet."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("enterprise-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("enterprise-agent", tier="enterprise")
    return key_info["key"]


async def test_metrics_enterprise_key_returns_200(client, enterprise_api_key, monkeypatch):
    """Enterprise tier can access /v1/metrics from any IP."""
    # Restrict IP allowlist so only tier auth grants access
    monkeypatch.setenv("METRICS_ALLOWED_IPS", "10.0.0.1")
    resp = await client.get(
        "/v1/metrics",
        headers={"Authorization": f"Bearer {enterprise_api_key}"},
    )
    assert resp.status_code == 200


async def test_metrics_pro_key_returns_403(client, pro_api_key, monkeypatch):
    """Pro tier without allowed IP gets 403."""
    monkeypatch.setenv("METRICS_ALLOWED_IPS", "10.0.0.1")
    resp = await client.get(
        "/v1/metrics",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 403


async def test_metrics_free_key_returns_403(client, api_key, monkeypatch):
    """Free tier without allowed IP gets 403."""
    monkeypatch.setenv("METRICS_ALLOWED_IPS", "10.0.0.1")
    resp = await client.get(
        "/v1/metrics",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


async def test_metrics_no_key_localhost_returns_200(client):
    """No auth + localhost IP still works (monitoring infra)."""
    resp = await client.get("/v1/metrics")
    # httpx ASGITransport uses 127.0.0.1 as client IP — in default allowlist
    assert resp.status_code == 200


async def test_metrics_no_key_external_returns_403(client, monkeypatch):
    """No auth + external IP gets 403."""
    monkeypatch.setenv("METRICS_ALLOWED_IPS", "10.0.0.1")
    resp = await client.get("/v1/metrics")
    # Client IP is 127.0.0.1 which is not in the allowlist
    assert resp.status_code == 403


async def test_metrics_admin_key_returns_200(client, admin_api_key, monkeypatch):
    """Admin key (which exceeds enterprise tier) can access metrics."""
    monkeypatch.setenv("METRICS_ALLOWED_IPS", "10.0.0.1")
    resp = await client.get(
        "/v1/metrics",
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200
