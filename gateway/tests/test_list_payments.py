"""Tests for P2-3: list_intents and list_escrows tools."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestListIntents:
    """Tests for the list_intents tool."""

    async def test_list_intents_exists(self, client, api_key):
        """list_intents should be recognized as a valid tool."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_intents",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_list_intents_empty(self, client, api_key):
        """list_intents returns empty list when no intents exist."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_intents",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["intents"] == []
        assert data["count"] == 0

    async def test_list_intents_after_create(self, client, app, api_key):
        """list_intents returns intents after creating one."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-li", initial_balance=100.0, signup_bonus=False)

        # Create an intent
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {"payer": "test-agent", "payee": "payee-li", "amount": 10.0},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

        # List intents
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_intents",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    async def test_list_intents_ownership_enforced(self, client, api_key):
        """list_intents for a different agent should be forbidden."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_intents",
                "params": {"agent_id": "other-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403


class TestListEscrows:
    """Tests for the list_escrows tool."""

    async def test_list_escrows_exists(self, client, api_key):
        """list_escrows should be recognized as a valid tool."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_escrows",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_list_escrows_empty(self, client, api_key):
        """list_escrows returns empty list when no escrows exist."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_escrows",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["escrows"] == []
        assert data["count"] == 0

    async def test_list_escrows_ownership_enforced(self, client, api_key):
        """list_escrows for a different agent should be forbidden."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "list_escrows",
                "params": {"agent_id": "other-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 403
