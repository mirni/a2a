"""Batch 3 — P1 Pagination tests (Items 9-11).

Item 9: get_messages — add offset
Item 10: search_servers — add offset
Item 11: get_webhook_deliveries — add offset
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _exec(client, tool, params, key):
    return await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {key}"},
    )


# ============================================================================
# Item 9: get_messages — add offset
# ============================================================================


class TestGetMessagesOffset:
    """get_messages should support offset parameter for pagination."""

    async def test_get_messages_with_offset(self, client, app):
        """Store 5 messages, get_messages(limit=2, offset=2) returns 2 starting from 3rd."""
        ctx = app.state.ctx
        key = await _create_agent(app, "msg-offset-agent", tier="free", balance=1000.0)

        # Send 5 messages
        for i in range(5):
            await ctx.messaging_api.send_message(
                sender="msg-offset-agent",
                recipient="someone",
                message_type="text",
                subject=f"msg-{i}",
                body=f"body-{i}",
            )

        # Get all messages
        resp_all = await _exec(
            client,
            "get_messages",
            {"agent_id": "msg-offset-agent", "limit": 50},
            key,
        )
        all_msgs = resp_all.json()["messages"]
        assert len(all_msgs) == 5

        # Get with offset=2
        resp = await _exec(
            client,
            "get_messages",
            {"agent_id": "msg-offset-agent", "limit": 2, "offset": 2},
            key,
        )
        assert resp.status_code == 200
        messages = resp.json()["messages"]
        assert len(messages) == 2
        # Offset=2 should skip first 2 (newest-first) and return the 3rd and 4th
        assert messages[0] != all_msgs[0]
        assert messages[0] != all_msgs[1]


# ============================================================================
# Item 10: search_servers — add offset
# ============================================================================


class TestSearchServersOffset:
    """search_servers should support offset parameter for pagination."""

    async def test_search_servers_with_offset(self, client, app):
        """Register 5 servers, search(limit=2, offset=2) returns 2."""
        ctx = app.state.ctx
        key = await _create_agent(app, "trust-offset-agent", tier="free", balance=1000.0)

        for i in range(5):
            await ctx.trust_api.register_server(name=f"server-{i}", url=f"https://server-{i}.example.com")

        resp = await _exec(
            client,
            "search_servers",
            {"limit": 2, "offset": 2},
            key,
        )
        assert resp.status_code == 200
        servers = resp.json()["servers"]
        assert len(servers) == 2


# ============================================================================
# Item 11: get_webhook_deliveries — add offset
# ============================================================================


class TestWebhookDeliveriesOffset:
    """get_webhook_deliveries should support offset parameter for pagination."""

    async def test_get_webhook_deliveries_with_offset(self, client, app):
        """Create 5 deliveries, query with offset=2 returns correct slice."""
        ctx = app.state.ctx
        key = await _create_agent(app, "wh-offset-agent", tier="pro", balance=5000.0)

        wh = await ctx.webhook_manager.register(
            agent_id="wh-offset-agent",
            url="https://example.com/hook",
            event_types=["billing.deposit"],
            secret="s3cret",
        )
        webhook_id = wh["id"]

        for i in range(5):
            await ctx.webhook_manager._insert_delivery(
                webhook_id=webhook_id,
                event_type="billing.deposit",
                payload_json='{"type": "billing.deposit"}',
                now=1000.0 + i,
            )

        resp = await _exec(
            client,
            "get_webhook_deliveries",
            {"webhook_id": webhook_id, "limit": 2, "offset": 2},
            key,
        )
        assert resp.status_code == 200
        deliveries = resp.json()["deliveries"]
        assert len(deliveries) == 2
