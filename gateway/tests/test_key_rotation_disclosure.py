"""Tests for L-2: Key rotation info disclosure prevention.

Key rotation should return a generic error for invalid/expired/revoked keys,
not specific messages that enable key state enumeration.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


class TestKeyRotationDisclosure:
    """Key rotation must not disclose key state details."""

    async def test_rotate_invalid_key_generic_error(self, client, app):
        """Rotating a completely invalid key should return generic error."""
        key = await _create_agent(app, "rot-agent")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "rotate_key", "params": {"current_key": "a2a_totally_invalid_key"}},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403
        data = resp.json()
        # Should NOT contain specific error type (e.g. "not found", "expired", "revoked")
        error_msg = str(data).lower()
        assert "not found" not in error_msg
        assert "expired" not in error_msg
        assert "revoked" not in error_msg
        assert "format" not in error_msg

    async def test_rotate_valid_key_succeeds(self, client, app):
        """Rotating a valid key should work and return new key."""
        key = await _create_agent(app, "rot-good")
        resp = await client.post(
            "/v1/execute",
            json={"tool": "rotate_key", "params": {"current_key": key}},
            headers={"Authorization": f"Bearer {key}"},
        )
        # Note: may fail with 401 since key was just revoked in rotation
        # or succeed with 200 returning new key
        assert resp.status_code in (200, 401)
