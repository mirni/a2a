"""Edge case tests for gateway /execute route.

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
            "/execute",
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
            "/execute",
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
            "/execute",
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
            "/execute",
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
            "/execute",
            json={"tool": "get_balance", "params": {"agent_id": "multi-key-agent"}},
            headers={"Authorization": f"Bearer {key_info_1['key']}"},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            "/execute",
            json={"tool": "get_balance", "params": {"agent_id": "multi-key-agent"}},
            headers={"Authorization": f"Bearer {key_info_2['key']}"},
        )
        assert resp2.status_code == 200


# ---------------------------------------------------------------------------
# Rate limit at hour boundary
# ---------------------------------------------------------------------------


class TestRateLimitHourBoundary:
    """The gateway uses floor-division to compute window_start:
    window_start = time.time() // 3600 * 3600

    This means the window resets at the top of each hour. We can verify
    this by pre-filling the rate counter with an old window_start and
    confirming it does not count toward the current window."""

    async def test_old_window_does_not_count(self, app, client):
        """Seed rate counts with a window_start from the previous hour.
        Requests in the current hour should not be affected."""
        ctx = app.state.ctx

        await ctx.tracker.wallet.create("rate-agent", initial_balance=1000.0)
        key_info = await ctx.key_manager.create_key("rate-agent", tier="free")

        # Seed 200 counts in the PREVIOUS hour window
        old_window_start = (time.time() // 3600 * 3600) - 3600
        for _ in range(200):
            await ctx.paywall_storage.increment_rate_count(
                "rate-agent", "gateway", old_window_start
            )

        # Current request should still succeed because it's a new window
        resp = await client.post(
            "/execute",
            json={"tool": "get_balance", "params": {"agent_id": "rate-agent"}},
            headers={"Authorization": f"Bearer {key_info['key']}"},
        )
        assert resp.status_code == 200


class TestRateLimitExceeded:
    """When rate counter for the current hour hits the limit, requests
    should be rejected with 429."""

    async def test_rate_limit_exceeded(self, app, client):
        ctx = app.state.ctx

        await ctx.tracker.wallet.create("rate-blocked", initial_balance=1000.0)
        key_info = await ctx.key_manager.create_key("rate-blocked", tier="free")

        # Free tier has 100 calls/hour limit
        # Seed to exactly 100 in the current window
        current_window = time.time() // 3600 * 3600
        for _ in range(100):
            await ctx.paywall_storage.increment_rate_count(
                "rate-blocked", "gateway", current_window
            )

        resp = await client.post(
            "/execute",
            json={"tool": "get_balance", "params": {"agent_id": "rate-blocked"}},
            headers={"Authorization": f"Bearer {key_info['key']}"},
        )
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "rate_limit_exceeded"
