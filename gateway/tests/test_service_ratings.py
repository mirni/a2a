"""Tests for P3-20: Service Ratings/Reviews (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_test_service(app) -> str:
    """Helper to create a service and return its ID."""
    from marketplace_src.models import PricingModel, PricingModelType, ServiceCreate

    ctx = app.state.ctx
    spec = ServiceCreate(
        provider_id="provider-1",
        name="Test Service",
        description="A test service for rating",
        category="analytics",
        tools=[],
        tags=["test"],
        endpoint="https://example.com/api",
        pricing=PricingModel(model=PricingModelType.PER_CALL, cost=1.0),
    )
    service = await ctx.marketplace.register_service(spec)
    return service.id


async def test_rate_service_basic(client, api_key, app):
    """Rate a service with a score of 5."""
    service_id = await _create_test_service(app)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "rate_service",
            "params": {
                "service_id": service_id,
                "agent_id": "test-agent",
                "rating": 5,
                "review": "Excellent service!",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["service_id"] == service_id
    assert result["agent_id"] == "test-agent"
    assert result["rating"] == 5


async def test_rate_service_upsert(client, api_key, app):
    """Second rating from same agent updates the existing one."""
    service_id = await _create_test_service(app)

    # First rating
    await client.post(
        "/v1/execute",
        json={
            "tool": "rate_service",
            "params": {
                "service_id": service_id,
                "agent_id": "test-agent",
                "rating": 3,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Second rating — should overwrite
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "rate_service",
            "params": {
                "service_id": service_id,
                "agent_id": "test-agent",
                "rating": 5,
                "review": "Changed my mind, great!",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["rating"] == 5

    # Verify only one rating exists
    resp2 = await client.post(
        "/v1/execute",
        json={
            "tool": "get_service_ratings",
            "params": {"service_id": service_id},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 200
    result = resp2.json()["result"]
    assert result["count"] == 1
    assert result["average_rating"] == 5.0


async def test_get_service_ratings_empty(client, api_key, app):
    """Get ratings for a service with no ratings."""
    service_id = await _create_test_service(app)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_service_ratings",
            "params": {"service_id": service_id},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["average_rating"] == 0
    assert result["count"] == 0
    assert result["ratings"] == []


async def test_get_service_ratings_average(client, api_key, app):
    """Average rating should be calculated correctly from multiple ratings."""
    service_id = await _create_test_service(app)
    ctx = app.state.ctx

    # We need multiple agents to rate — directly insert via the tool function
    # First, create additional wallets/keys for different agents
    await ctx.tracker.wallet.create("agent-a", initial_balance=100, signup_bonus=False)
    key_a = await ctx.key_manager.create_key("agent-a", tier="free")

    await ctx.tracker.wallet.create("agent-b", initial_balance=100, signup_bonus=False)
    key_b = await ctx.key_manager.create_key("agent-b", tier="free")

    # Rate with agent-a: 4
    await client.post(
        "/v1/execute",
        json={
            "tool": "rate_service",
            "params": {
                "service_id": service_id,
                "agent_id": "agent-a",
                "rating": 4,
            },
        },
        headers={"Authorization": f"Bearer {key_a['key']}"},
    )

    # Rate with agent-b: 2
    await client.post(
        "/v1/execute",
        json={
            "tool": "rate_service",
            "params": {
                "service_id": service_id,
                "agent_id": "agent-b",
                "rating": 2,
            },
        },
        headers={"Authorization": f"Bearer {key_b['key']}"},
    )

    # Get ratings
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_service_ratings",
            "params": {"service_id": service_id},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["count"] == 2
    assert result["average_rating"] == 3.0  # (4+2)/2


async def test_rate_service_invalid_rating(client, api_key, app):
    """Rating outside 1-5 should fail."""
    service_id = await _create_test_service(app)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "rate_service",
            "params": {
                "service_id": service_id,
                "agent_id": "test-agent",
                "rating": 6,
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # The tool should return an error (either 400 from handler or error in result)
    body = resp.json()
    if resp.status_code == 200:
        assert "error" in body.get("result", {})
    else:
        assert resp.status_code in (400, 500)
