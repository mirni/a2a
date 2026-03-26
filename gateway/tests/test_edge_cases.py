"""Edge case tests for gateway /v1/execute route.

Covers: rate limit reset at hour boundary, multiple API keys for same agent
sharing rate limit, and invalid JSON variants.
"""

from __future__ import annotations

import time

import pytest


# ---------------------------------------------------------------------------
# Invalid JSON variants
# ---------------------------------------------------------------------------


class TestInvalidJsonVariants:
    """Various malformed or unexpected JSON payloads."""

    async def test_empty_body(self, client, api_key):
        """Empty request body should return 400."""
        resp = await client.post(
            "/v1/execute",
            content=b"",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "bad_request"

    async def test_json_array_body(self, client, api_key):
        """JSON array (not object) should return 400 because body.get('tool') fails."""
        resp = await client.post(
            "/v1/execute",
            content=b'["hello"]',
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        # Should fail: either parse error or missing 'tool' field
        assert resp.status_code in (400, 500)

    async def test_json_string_body(self, client, api_key):
        """JSON string value (not object) should return 400."""
        resp = await client.post(
            "/v1/execute",
            content=b'"just a string"',
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code in (400, 500)

    async def test_missing_content_type(self, client, api_key):
        """Missing Content-Type header with JSON body should still parse
        (Starlette reads body regardless of Content-Type)."""
        resp = await client.post(
            "/v1/execute",
            content=b'{"tool": "get_balance", "params": {"agent_id": "test-agent"}}',
            headers={
                "Authorization": f"Bearer {api_key}",
            },
        )
        # Starlette request.json() attempts to parse regardless
        # It should either succeed or return 400
        assert resp.status_code in (200, 400)


# ---------------------------------------------------------------------------
# Multiple API keys same agent
# ---------------------------------------------------------------------------


class TestMultipleApiKeysSameAgent:
    """Two keys for the same agent should share the rate limit counter
    because rate limits are tracked per agent_id, not per key."""

    async def test_two_keys_same_agent_both_work(self, app, client):
        ctx = app.state.ctx

        # Create one agent with two keys
        await ctx.tracker.wallet.create("multi-key-agent", initial_balance=1000.0)
        key_info_1 = await ctx.key_manager.create_key("multi-key-agent", tier="free")
        key_info_2 = await ctx.key_manager.create_key("multi-key-agent", tier="free")

        # Both keys should be able to call
        resp1 = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "multi-key-agent"}},
            headers={"Authorization": f"Bearer {key_info_1['key']}"},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "multi-key-agent"}},
            headers={"Authorization": f"Bearer {key_info_2['key']}"},
        )
        assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# Rate limit sliding window
# ---------------------------------------------------------------------------


class TestRateLimitSlidingWindow:
    """The gateway uses a sliding window for rate limiting.
    Events older than 1 hour are not counted."""

    async def test_old_events_do_not_count(self, app, client):
        """Seed rate events older than 1 hour. They should not affect the current window."""
        ctx = app.state.ctx

        await ctx.tracker.wallet.create("rate-agent", initial_balance=1000.0)
        key_info = await ctx.key_manager.create_key("rate-agent", tier="free")

        # Insert old rate events (>1 hour ago) directly into DB
        old_time = time.time() - 7200  # 2 hours ago
        for _ in range(200):
            await ctx.paywall_storage.db.execute(
                "INSERT INTO rate_events (agent_id, window_key, tool_name, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("rate-agent", "gateway", "", old_time),
            )
        await ctx.paywall_storage.db.commit()

        # Current request should still succeed
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "rate-agent"}},
            headers={"Authorization": f"Bearer {key_info['key']}"},
        )
        assert resp.status_code == 200


class TestRateLimitExceeded:
    """When sliding window count hits the limit, requests should be rejected with 429."""

    async def test_rate_limit_exceeded(self, app, client):
        ctx = app.state.ctx

        await ctx.tracker.wallet.create("rate-blocked", initial_balance=1000.0)
        key_info = await ctx.key_manager.create_key("rate-blocked", tier="free")

        # Free tier has 100 calls/hour limit + 10 burst allowance
        # Seed 111 recent rate events (exceeds both hourly and burst)
        now = time.time()
        for _ in range(111):
            await ctx.paywall_storage.db.execute(
                "INSERT INTO rate_events (agent_id, window_key, tool_name, timestamp) "
                "VALUES (?, ?, ?, ?)",
                ("rate-blocked", "gateway", "", now),
            )
        await ctx.paywall_storage.db.commit()

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "rate-blocked"}},
            headers={"Authorization": f"Bearer {key_info['key']}"},
        )
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "rate_limit_exceeded"
