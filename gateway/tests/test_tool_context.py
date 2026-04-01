"""Tests for gateway.src.deps.tool_context — require_tool chain + finalize_response."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# require_tool: error paths
# ---------------------------------------------------------------------------


async def test_unknown_tool_returns_400(client, api_key):
    """Tool not in catalog -> 400."""
    # The /v1/execute endpoint routes through require_tool indirectly.
    # We test directly via a known non-existent v1 route.
    resp = await client.post(
        "/v1/execute",
        json={"tool": "nonexistent_tool_xyz", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert (
        body.get("code") == "unknown_tool"
        or "unknown" in body.get("detail", "").lower()
        or "Unknown" in body.get("detail", "")
    )


async def test_missing_api_key_returns_401(client):
    """No auth -> 401."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
    )
    assert resp.status_code == 401


async def test_invalid_api_key_returns_401(client):
    """Bad key -> 401."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": "Bearer bad-key-12345"},
    )
    assert resp.status_code == 401


async def test_admin_only_tool_non_admin_returns_403(client, api_key):
    """Non-admin hitting admin tool -> 403."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "backup_database", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # 403 admin_only or equivalent
    assert resp.status_code == 403


async def test_tier_insufficient_returns_403(client, api_key):
    """Free tier on a pro-only tool -> 403."""
    # register_webhook requires pro tier
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "test-agent",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


async def test_insufficient_balance_returns_402(app, client):
    """Zero balance + non-zero cost -> 402."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("broke-agent", initial_balance=0.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("broke-agent", tier="free")
    key = key_info["key"]

    # best_match costs 0.1 credits and is free tier
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "best_match",
            "params": {
                "agent_id": "broke-agent",
                "query": "test",
            },
        },
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 402


# ---------------------------------------------------------------------------
# finalize_response: headers
# ---------------------------------------------------------------------------


async def test_finalize_response_builds_headers(client, api_key):
    """X-Charged, X-Request-ID, rate-limit headers on success."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers
    assert "X-RateLimit-Limit" in resp.headers


async def test_finalize_response_pagination_link_header(client, pro_api_key, app):
    """has_more + next_cursor -> Link header with rel=next."""
    # Register several services via the API so pagination kicks in
    for i in range(3):
        await client.post(
            "/v1/execute",
            json={
                "tool": "register_service",
                "params": {
                    "agent_id": "pro-agent",
                    "name": f"link-svc-{i}",
                    "description": "Test service",
                    "category": "test",
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )

    resp = await client.get(
        "/v1/marketplace/services",
        params={"limit": 1, "paginate": "true"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    if body.get("has_more"):
        assert "Link" in resp.headers
        assert 'rel="next"' in resp.headers["Link"]


# ---------------------------------------------------------------------------
# check_ownership
# ---------------------------------------------------------------------------


async def test_check_ownership_violation_returns_403(client, api_key):
    """Accessing another agent's resource -> 403."""
    resp = await client.get(
        "/v1/billing/wallets/other-agent/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Ownership check prevents accessing other agent's wallet
    assert resp.status_code == 403


async def test_admin_bypasses_ownership(app, client):
    """Admin tier can access any agent's resources."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("admin-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("admin-agent", tier="pro", scopes=["read", "write", "admin"])
    admin_key = key_info["key"]

    # Create the target wallet too
    await ctx.tracker.wallet.create("target-agent", initial_balance=100.0, signup_bonus=False)

    resp = await client.get(
        "/v1/billing/wallets/target-agent/balance",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
