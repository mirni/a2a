"""Tests for P2 #21: Agent_id path max-length validation.

Agent IDs longer than 128 characters should be rejected with 400 and an RFC
9457 typed error URI (audit M3 — was 422 about:blank).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestAgentIdMaxLength:
    """Agent IDs in path params must be <= 128 characters."""

    async def test_normal_agent_id_accepted(self, client, api_key):
        """Normal-length agent_id should work fine."""
        resp = await client.get(
            "/v1/billing/wallets/test-agent/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200

    async def test_oversized_agent_id_rejected(self, client, api_key):
        """200+ char agent_id should return 400 with typed URI (not about:blank)."""
        long_id = "a" * 200
        resp = await client.get(
            f"/v1/billing/wallets/{long_id}/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        assert resp.headers.get("content-type", "").startswith("application/problem+json")
        body = resp.json()
        assert body["type"] == "https://api.greenhelix.net/errors/path-too-long"
        assert body["type"] != "about:blank"
        assert body["status"] == 400

    async def test_128_char_agent_id_accepted(self, client, api_key):
        """Exactly 128 chars should be accepted."""
        exact_id = "b" * 128
        # This will 403 because the agent doesn't exist/doesn't match, but NOT 400
        resp = await client.get(
            f"/v1/billing/wallets/{exact_id}/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should not be 400 — 403 is expected (ownership check failure)
        assert resp.status_code != 400

    async def test_129_char_agent_id_rejected(self, client, api_key):
        """129 chars should be rejected with 400 and typed URI."""
        long_id = "c" * 129
        resp = await client.get(
            f"/v1/billing/wallets/{long_id}/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "https://api.greenhelix.net/errors/path-too-long"
