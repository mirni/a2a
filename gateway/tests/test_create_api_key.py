"""Tests for P2-17: Self-Service API Key Creation tool (create_api_key)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestCreateApiKey:
    """Tests for the create_api_key tool."""

    async def test_tool_exists_in_catalog(self, client, api_key):
        """create_api_key should be in the catalog."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_create_key_for_self(self, client, api_key):
        """An agent should be able to create a key for themselves."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (200, 201)
        result = resp.json()
        assert "key" in result
        assert result["agent_id"] == "test-agent"
        assert "tier" in result
        assert "created_at" in result
        # The key should be a valid a2a_ format key
        assert result["key"].startswith("a2a_")

    async def test_create_key_with_explicit_tier(self, client, api_key):
        """Should allow specifying a tier for the new key."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "test-agent", "tier": "free"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["tier"] == "free"

    async def test_created_key_is_valid(self, client, api_key, app):
        """A newly created key should be usable for API calls."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "test-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code in (200, 201)
        new_key = resp.json()["key"]

        # Use the new key
        resp2 = await client.post(
            "/v1/execute",
            json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
            headers={"Authorization": f"Bearer {new_key}"},
        )
        assert resp2.status_code == 200

    async def test_cannot_create_key_for_different_agent(self, client, api_key):
        """Should reject creating a key for a different agent (non-admin)."""
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_api_key",
                "params": {"agent_id": "other-agent"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should be forbidden for a non-admin user
        assert resp.status_code == 403

    async def test_missing_agent_id_param(self, client, api_key):
        """Should fail when agent_id param is missing."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "create_api_key", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
