"""Tests for P2-4: offset/cursor pagination on list endpoints.

Verifies that list tools support offset/limit parameters and return
pagination metadata when ``paginate=true`` is passed.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _exec(client, api_key, tool: str, params: dict):
    """Execute a tool and return the parsed JSON body."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# list_api_keys pagination
# ---------------------------------------------------------------------------


async def test_list_api_keys_paginate_first_page(client, app, api_key):
    """list_api_keys with paginate=true, offset=0, limit=2 returns first 2 keys."""
    ctx = app.state.ctx
    # Create additional keys so we have at least 4 (1 already created by fixture)
    for _ in range(3):
        await ctx.key_manager.create_key("test-agent", tier="free")

    body = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
            "offset": 0,
            "limit": 2,
            "paginate": True,
        },
    )

    assert "items" in body, "Paginated response must contain 'items'"
    assert "total" in body, "Paginated response must contain 'total'"
    assert "offset" in body, "Paginated response must contain 'offset'"
    assert "limit" in body, "Paginated response must contain 'limit'"
    assert "has_more" in body, "Paginated response must contain 'has_more'"

    assert len(body["items"]) == 2
    assert body["total"] >= 4
    assert body["offset"] == 0
    assert body["limit"] == 2
    assert body["has_more"] is True


async def test_list_api_keys_paginate_second_page(client, app, api_key):
    """list_api_keys with offset=2, limit=2 returns next 2 keys."""
    ctx = app.state.ctx
    for _ in range(3):
        await ctx.key_manager.create_key("test-agent", tier="free")

    body = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
            "offset": 2,
            "limit": 2,
            "paginate": True,
        },
    )

    assert len(body["items"]) == 2
    assert body["offset"] == 2
    assert body["limit"] == 2
    assert body["total"] >= 4


async def test_list_api_keys_without_paginate_returns_flat(client, app, api_key):
    """Without paginate=true, list_api_keys returns legacy flat format."""
    body = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
        },
    )

    # Legacy format: {"keys": [...]}
    assert "keys" in body
    assert "items" not in body


async def test_list_api_keys_paginate_metadata_total(client, app, api_key):
    """Pagination metadata 'total' accurately reflects the total key count."""
    ctx = app.state.ctx
    # We start with 1 key from fixture, add 4 more = 5 total
    for _ in range(4):
        await ctx.key_manager.create_key("test-agent", tier="free")

    body = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
            "offset": 0,
            "limit": 100,
            "paginate": True,
        },
    )

    assert body["total"] == 5
    assert len(body["items"]) == 5
    assert body["has_more"] is False


# ---------------------------------------------------------------------------
# search_services pagination
# ---------------------------------------------------------------------------


async def test_search_services_paginate(client, app, api_key):
    """search_services with paginate=true returns paginated response."""
    ctx = app.state.ctx
    # Register several services
    from marketplace_src.models import PricingModel, PricingModelType, ServiceCreate

    for i in range(5):
        spec = ServiceCreate(
            provider_id="provider-1",
            name=f"Service {i}",
            description=f"Test service number {i}",
            category="analytics",
            tools=[],
            tags=["test"],
            endpoint=f"https://example.com/svc{i}",
            pricing=PricingModel(model=PricingModelType.FREE),
        )
        await ctx.marketplace.register_service(spec)

    body = await _exec(
        client,
        api_key,
        "search_services",
        {
            "category": "analytics",
            "offset": 0,
            "limit": 2,
            "paginate": True,
        },
    )

    assert "items" in body
    assert "total" in body
    assert len(body["items"]) == 2
    assert body["total"] >= 5
    assert body["offset"] == 0
    assert body["limit"] == 2
    assert body["has_more"] is True


async def test_search_services_offset_returns_different_subset(client, app, api_key):
    """search_services with different offsets returns different items."""
    ctx = app.state.ctx
    from marketplace_src.models import PricingModel, PricingModelType, ServiceCreate

    for i in range(4):
        spec = ServiceCreate(
            provider_id="provider-1",
            name=f"OffsetSvc {i}",
            description=f"Offset test service {i}",
            category="data",
            tools=[],
            tags=["offset-test"],
            endpoint=f"https://example.com/offset{i}",
            pricing=PricingModel(model=PricingModelType.FREE),
        )
        await ctx.marketplace.register_service(spec)

    body_page1 = await _exec(
        client,
        api_key,
        "search_services",
        {
            "category": "data",
            "offset": 0,
            "limit": 2,
            "paginate": True,
        },
    )
    body_page2 = await _exec(
        client,
        api_key,
        "search_services",
        {
            "category": "data",
            "offset": 2,
            "limit": 2,
            "paginate": True,
        },
    )

    page1_ids = {s["id"] for s in body_page1["items"]}
    page2_ids = {s["id"] for s in body_page2["items"]}

    # Pages must not overlap
    assert page1_ids.isdisjoint(page2_ids), "Paginated pages must return different items"


async def test_search_services_without_paginate_returns_flat(client, app, api_key):
    """Without paginate=true, search_services returns legacy flat format."""
    body = await _exec(
        client,
        api_key,
        "search_services",
        {
            "category": "analytics",
        },
    )
    assert "services" in body
    assert "items" not in body


# ---------------------------------------------------------------------------
# search_agents pagination
# ---------------------------------------------------------------------------


async def test_search_agents_paginate(client, app, api_key):
    """search_agents with paginate=true returns paginated response."""
    ctx = app.state.ctx
    from marketplace_src.models import PricingModel, PricingModelType, ServiceCreate

    # Register services under different providers to make multiple agents discoverable
    for i in range(4):
        spec = ServiceCreate(
            provider_id=f"agent-{i}",
            name=f"ML Service {i}",
            description=f"Machine learning service {i}",
            category="ml",
            tools=[],
            tags=["ml"],
            endpoint=f"https://example.com/ml{i}",
            pricing=PricingModel(model=PricingModelType.FREE),
        )
        await ctx.marketplace.register_service(spec)

    body = await _exec(
        client,
        api_key,
        "search_agents",
        {
            "query": "ml",
            "offset": 0,
            "limit": 2,
            "paginate": True,
        },
    )

    assert "items" in body
    assert "total" in body
    assert len(body["items"]) == 2
    assert body["total"] >= 4
    assert body["has_more"] is True


# ---------------------------------------------------------------------------
# list_webhooks pagination
# ---------------------------------------------------------------------------


async def test_list_webhooks_paginate(client, app, pro_api_key):
    """list_webhooks with paginate=true returns paginated response."""
    ctx = app.state.ctx
    for i in range(4):
        await ctx.webhook_manager.register(
            agent_id="pro-agent",
            url=f"https://example.com/hook{i}",
            event_types=["payment.created"],
            secret=f"secret-{i}",
        )

    body = await _exec(
        client,
        pro_api_key,
        "list_webhooks",
        {
            "agent_id": "pro-agent",
            "offset": 0,
            "limit": 2,
            "paginate": True,
        },
    )

    assert "items" in body
    assert "total" in body
    assert len(body["items"]) == 2
    assert body["total"] >= 4
    assert body["has_more"] is True


async def test_list_webhooks_without_paginate_returns_flat(client, app, pro_api_key):
    """Without paginate=true, list_webhooks returns legacy flat format."""
    ctx = app.state.ctx
    await ctx.webhook_manager.register(
        agent_id="pro-agent",
        url="https://example.com/hook-flat",
        event_types=["payment.created"],
        secret="secret-flat",
    )

    body = await _exec(
        client,
        pro_api_key,
        "list_webhooks",
        {
            "agent_id": "pro-agent",
        },
    )
    assert "webhooks" in body
    assert "items" not in body


# ---------------------------------------------------------------------------
# Negative tests
# ---------------------------------------------------------------------------


async def test_paginate_with_negative_offset_returns_error_or_empty(client, app, api_key):
    """Negative offset should be treated as 0."""
    body = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
            "offset": -1,
            "limit": 10,
            "paginate": True,
        },
    )
    # Should clamp to 0
    assert body["offset"] == 0


async def test_paginate_with_zero_limit(client, app, api_key):
    """limit=0 with paginate should return empty items but correct total."""
    body = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
            "offset": 0,
            "limit": 0,
            "paginate": True,
        },
    )
    assert body["items"] == []
    assert body["total"] >= 1
    assert body["limit"] == 0
