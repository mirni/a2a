"""Tests for P2-4: offset/cursor pagination on list endpoints.

Verifies that list tools support offset/limit parameters and return
pagination metadata when ``paginate=true`` is passed.
"""

from __future__ import annotations

import pytest

from gateway.src.tools._pagination import _paginate, decode_cursor, encode_cursor

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Unit tests for encode_cursor / decode_cursor
# ---------------------------------------------------------------------------


class TestCursorCodec:
    def test_roundtrip(self):
        for offset in (0, 1, 50, 9999):
            assert decode_cursor(encode_cursor(offset)) == offset

    def test_malformed_base64_returns_0(self):
        assert decode_cursor("!!!not-base64!!!") == 0

    def test_wrong_prefix_returns_0(self):
        import base64

        bad = base64.urlsafe_b64encode(b"wrong:42").decode()
        assert decode_cursor(bad) == 0

    def test_negative_offset_clamped_to_0(self):
        import base64

        cursor = base64.urlsafe_b64encode(b"off:-5").decode()
        assert decode_cursor(cursor) == 0


class TestPaginate:
    def test_basic_pagination(self):
        items = list(range(10))
        result = _paginate(items, {"limit": 3, "offset": 0})
        assert result["items"] == [0, 1, 2]
        assert result["total"] == 10
        assert result["has_more"] is True
        assert "next_cursor" in result

    def test_last_page(self):
        items = list(range(5))
        result = _paginate(items, {"limit": 10, "offset": 0})
        assert result["items"] == [0, 1, 2, 3, 4]
        assert result["has_more"] is False
        assert "next_cursor" not in result

    def test_zero_limit(self):
        items = list(range(5))
        result = _paginate(items, {"limit": 0})
        assert result["items"] == []
        assert result["total"] == 5

    def test_offset_beyond_total(self):
        items = list(range(3))
        result = _paginate(items, {"limit": 10, "offset": 100})
        assert result["items"] == []
        assert result["has_more"] is False

    def test_total_override(self):
        items = [1, 2, 3]  # pre-sliced by storage
        result = _paginate(items, {"limit": 3, "offset": 0}, total_override=100)
        assert result["items"] == [1, 2, 3]
        assert result["total"] == 100
        assert result["has_more"] is True

    def test_cursor_overrides_offset(self):
        items = list(range(20))
        cursor = encode_cursor(5)
        result = _paginate(items, {"cursor": cursor, "limit": 3, "offset": 0})
        assert result["items"] == [5, 6, 7]
        assert result["offset"] == 5


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
    assert float(body["total"]) >= 4
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
    assert float(body["total"]) >= 4


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

    assert float(body["total"]) == 5
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
    assert float(body["total"]) >= 5
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
    assert float(body["total"]) >= 4
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
    assert float(body["total"]) >= 4
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
    assert float(body["total"]) >= 1
    assert body["limit"] == 0


# ---------------------------------------------------------------------------
# Cursor-based pagination (T9)
# ---------------------------------------------------------------------------


async def _exec_with_resp(client, api_key, tool: str, params: dict):
    """Execute a tool and return (body, response) for header inspection."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json(), resp


async def test_cursor_pagination_returns_next_cursor(client, app, api_key):
    """When has_more=True, response includes next_cursor."""
    ctx = app.state.ctx
    for _ in range(4):
        await ctx.key_manager.create_key("test-agent", tier="free")

    body, resp = await _exec_with_resp(
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

    assert body["has_more"] is True
    assert "next_cursor" in body, "Paginated response with has_more must include next_cursor"
    assert isinstance(body["next_cursor"], str)
    assert len(body["next_cursor"]) > 0


async def test_cursor_pagination_link_header(client, app, api_key):
    """When has_more=True, Link header with rel=next is present."""
    ctx = app.state.ctx
    for _ in range(4):
        await ctx.key_manager.create_key("test-agent", tier="free")

    body, resp = await _exec_with_resp(
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

    assert body["has_more"] is True
    link = resp.headers.get("link")
    assert link is not None, "Link header must be present when has_more=True"
    assert 'rel="next"' in link


async def test_cursor_pagination_using_cursor_param(client, app, api_key):
    """Using cursor param from page 1 returns page 2 items."""
    ctx = app.state.ctx
    for _ in range(4):
        await ctx.key_manager.create_key("test-agent", tier="free")

    # First page
    body1 = await _exec(
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
    assert body1["has_more"] is True
    cursor = body1["next_cursor"]

    # Second page using cursor
    body2 = await _exec(
        client,
        api_key,
        "list_api_keys",
        {
            "agent_id": "test-agent",
            "cursor": cursor,
            "limit": 2,
            "paginate": True,
        },
    )
    assert "items" in body2
    assert len(body2["items"]) > 0
    # Page 2 items should differ from page 1 (compare by key_hash_prefix)
    prefixes1 = {k["key_hash_prefix"] for k in body1["items"]}
    prefixes2 = {k["key_hash_prefix"] for k in body2["items"]}
    assert prefixes1.isdisjoint(prefixes2), "Cursor-based page 2 should not overlap page 1"


async def test_no_link_header_when_no_more_pages(client, app, api_key):
    """When has_more=False, no Link header and no next_cursor."""
    body, resp = await _exec_with_resp(
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

    assert body["has_more"] is False
    assert "next_cursor" not in body
    # /v1/execute is deprecated in v1.2.4 and always emits a Sunset Link
    # header (RFC 8594). The pagination contract is that there is no
    # ``rel="next"`` link on the terminal page, not that the Link header
    # is absent entirely.
    link_header = resp.headers.get("link") or ""
    assert 'rel="next"' not in link_header


async def test_pricing_cursor_pagination(client, app, api_key):
    """GET /v1/pricing with cursor param returns correct page."""
    # First page
    resp1 = await client.get(
        "/v1/pricing?limit=2&offset=0",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert len(body1["tools"]) == 2

    # If there are more tools, check Link header
    if body1.get("has_more") or body1.get("next_cursor"):
        cursor = body1["next_cursor"]
        resp2 = await client.get(
            f"/v1/pricing?cursor={cursor}&limit=2",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        names1 = {t["name"] for t in body1["tools"]}
        names2 = {t["name"] for t in body2["tools"]}
        assert names1.isdisjoint(names2)
