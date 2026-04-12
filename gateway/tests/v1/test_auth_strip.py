"""AUTH1.3 verification — API keys with whitespace are stripped correctly.

The v1.2.9 audit flagged that keys with spaces might be accepted without
stripping.  This was already fixed in v1.2.4 (auth.py lines 41, 48).
These tests verify the fix holds.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_bearer_key_with_trailing_space(client, api_key):
    """API key with trailing space should be accepted (stripped to valid key)."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer {api_key} "},
    )
    assert resp.status_code == 200, f"Key with trailing space rejected: {resp.status_code}"


async def test_bearer_key_with_leading_space(client, api_key):
    """API key with leading space should be accepted (stripped to valid key)."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer  {api_key}"},
    )
    assert resp.status_code == 200, f"Key with leading space rejected: {resp.status_code}"


async def test_bearer_key_with_tab(client, api_key):
    """API key surrounded by tabs should be stripped correctly."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": f"Bearer \t{api_key}\t"},
    )
    assert resp.status_code == 200


async def test_x_api_key_with_trailing_space(client, api_key):
    """X-API-Key with trailing whitespace should be stripped."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"X-API-Key": f"{api_key} "},
    )
    assert resp.status_code == 200


async def test_whitespace_only_key_rejected(client):
    """A whitespace-only key should not authenticate."""
    resp = await client.get(
        "/v1/billing/wallets/test-agent/balance",
        headers={"Authorization": "Bearer    "},
    )
    assert resp.status_code == 401
