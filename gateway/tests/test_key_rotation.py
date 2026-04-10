"""Tests for key rotation tool (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_rotate_key(client, api_key, app):
    """Rotate an API key: new key is returned and usable.

    v1.2.2 T-6: the old key is marked revoked but continues to
    authenticate for ``KEY_ROTATION_GRACE_SECONDS`` (300 s) so
    clients have time to swap in the new key without an outage.
    After the grace window elapses the old key is rejected.
    """
    import time as _time

    from paywall_src.keys import KEY_ROTATION_GRACE_SECONDS

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "rotate_key",
            "params": {"current_key": api_key},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert "new_key" in result
    assert result["new_key"] != api_key
    assert result["revoked"] is True

    # New key should work immediately
    resp3 = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {result['new_key']}"},
    )
    assert resp3.status_code == 200

    # Old key still works during the grace window
    resp_grace = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp_grace.status_code == 200

    # Backdate revoked_at past the grace window → old key now rejected
    ctx = app.state.ctx
    past = _time.time() - (KEY_ROTATION_GRACE_SECONDS + 1)
    await ctx.key_manager.storage.db.execute("UPDATE api_keys SET revoked_at = ? WHERE revoked = 1", (past,))
    await ctx.key_manager.storage.db.commit()

    resp2 = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 401


async def test_rotate_key_preserves_tier(client, pro_api_key, app):
    """Rotated key should maintain the same tier."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "rotate_key",
            "params": {"current_key": pro_api_key},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["tier"] == "pro"
