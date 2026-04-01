"""Tests for P1-8: Webhook delivery history via get_webhook_deliveries tool."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_get_webhook_deliveries_returns_empty_list(client, pro_api_key, app):
    """Querying deliveries for a webhook with no deliveries returns empty list."""
    ctx = app.state.ctx
    # Register a webhook first
    wh = await ctx.webhook_manager.register(
        agent_id="pro-agent",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
    )
    webhook_id = wh["id"]

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_webhook_deliveries", "params": {"webhook_id": webhook_id}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["deliveries"] == []


async def test_get_webhook_deliveries_returns_delivery_records(client, pro_api_key, app):
    """After inserting a delivery record, it appears in the history."""
    ctx = app.state.ctx
    wh = await ctx.webhook_manager.register(
        agent_id="pro-agent",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
    )
    webhook_id = wh["id"]

    # Insert a delivery record directly
    await ctx.webhook_manager._insert_delivery(
        webhook_id=webhook_id,
        event_type="billing.deposit",
        payload_json='{"type": "billing.deposit"}',
        now=1000.0,
    )

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_webhook_deliveries", "params": {"webhook_id": webhook_id}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    deliveries = body["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["webhook_id"] == webhook_id
    assert deliveries[0]["event_type"] == "billing.deposit"
    assert deliveries[0]["status"] == "pending"
    assert deliveries[0]["attempts"] == 0


async def test_get_webhook_deliveries_respects_limit(client, pro_api_key, app):
    """The limit parameter caps the number of returned deliveries."""
    ctx = app.state.ctx
    wh = await ctx.webhook_manager.register(
        agent_id="pro-agent",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
    )
    webhook_id = wh["id"]

    # Insert 5 delivery records
    for i in range(5):
        await ctx.webhook_manager._insert_delivery(
            webhook_id=webhook_id,
            event_type="billing.deposit",
            payload_json='{"type": "billing.deposit"}',
            now=1000.0 + i,
        )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_webhook_deliveries",
            "params": {"webhook_id": webhook_id, "limit": 3},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["deliveries"]) == 3


async def test_get_webhook_deliveries_requires_pro_tier(client, api_key, app):
    """Free-tier keys should be able to access this tool (it is free-tier)."""
    ctx = app.state.ctx
    wh = await ctx.webhook_manager.register(
        agent_id="test-agent",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
    )
    webhook_id = wh["id"]

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_webhook_deliveries", "params": {"webhook_id": webhook_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # pro tier required tool should reject free-tier keys
    assert resp.status_code == 403


async def test_get_webhook_deliveries_missing_webhook_id(client, pro_api_key):
    """Missing webhook_id should return 400."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_webhook_deliveries", "params": {}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["type"].endswith("/missing-parameter")
