"""Tests for key rotation tool (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_rotate_key(client, api_key, app):
    """Rotate an API key: new key is returned and usable.

    v1.2.4 audit v1.2.3 MED-8: the old key continues to authenticate
    for ``KEY_ROTATION_GRACE_SECONDS`` (300 s) after rotation so
    clients have time to swap in the new key without an outage.
    Because the old key still works, the response must report
    ``revoked: False`` and expose ``grace_period_seconds`` and
    ``grace_expires_at``. After the grace window elapses the old key
    is rejected. (Previously the response claimed ``revoked: True``
    while the key still worked — a state-contract lie.)
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
    # MED-8: old key still works during grace window, so revoked must be False.
    assert result["revoked"] is False
    assert result["grace_period_seconds"] == KEY_ROTATION_GRACE_SECONDS
    assert "grace_expires_at" in result
    assert result["grace_expires_at"] >= _time.time()

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
