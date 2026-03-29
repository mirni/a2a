"""Tests for key rotation tool (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_rotate_key(client, api_key, app):
    """Rotate an API key: old key is revoked, new key is returned."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "rotate_key",
            "params": {"current_key": api_key},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "new_key" in result
    assert result["new_key"] != api_key
    assert result["revoked"] is True

    # Old key should no longer work
    resp2 = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp2.status_code == 401

    # New key should work
    resp3 = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {result['new_key']}"},
    )
    assert resp3.status_code == 200


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
    result = resp.json()["result"]
    assert result["tier"] == "pro"
