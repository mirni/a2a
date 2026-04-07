"""Tests for P2 #24: Identity returns 404 for non-existent agents.

get_agent_identity and get_agent_reputation should return 404 instead of
200 with {found: false}.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestIdentity404:
    """Non-existent agents should get 404, not 200 with found=false."""

    async def test_get_identity_nonexistent_returns_404(self, client, api_key):
        """get_agent_identity for unknown agent should return 404."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_identity", "params": {"agent_id": "does-not-exist-xyz"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 404

    async def test_get_reputation_nonexistent_returns_404(self, client, api_key):
        """get_agent_reputation for unknown agent should return 404."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_reputation", "params": {"agent_id": "does-not-exist-xyz"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 404

    async def test_get_identity_404_includes_registration_hint(self, client, api_key):
        """404 error for get_agent_identity should include registration hint."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_identity", "params": {"agent_id": "no-such-agent"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "Register identity first" in detail
        assert "/v1/identity/agents" in detail

    async def test_get_reputation_404_includes_registration_hint(self, client, api_key):
        """404 error for get_agent_reputation should include registration hint."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_reputation", "params": {"agent_id": "no-such-agent"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "Register identity first" in detail
        assert "/v1/identity/agents" in detail

    async def test_get_identity_existing_returns_200(self, client, api_key, app):
        """get_agent_identity for existing agent should return 200."""
        ctx = app.state.ctx
        await ctx.identity_api.register_agent(agent_id="exists-agent")

        resp = await client.post(
            "/v1/execute",
            json={"tool": "get_agent_identity", "params": {"agent_id": "exists-agent"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("found") is True
