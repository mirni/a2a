"""Tests for M2: transactions response must expose `type` and `timestamp` aliases.

Audit M2: the public API contract specifies fields `id, type, amount, timestamp,
description`. The raw DB columns are `tx_type` and `created_at`. We add both
names to the response for forward/backward compatibility.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_get_transactions_exposes_type_and_timestamp_aliases(client, api_key, app):
    """Response rows should include `type` and `timestamp` alongside raw column names."""
    # Make a deposit first so there is at least one transaction
    deposit_resp = await client.post(
        "/v1/billing/wallets/test-agent/deposit",
        json={"amount": 10.0, "description": "m2-alias-test"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert deposit_resp.status_code in (200, 201), deposit_resp.text

    resp = await client.get(
        "/v1/billing/wallets/test-agent/transactions",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    txns = body.get("transactions", [])
    assert len(txns) > 0
    tx = txns[0]
    # Both legacy and new field names present
    assert "tx_type" in tx
    assert "type" in tx
    assert tx["type"] == tx["tx_type"]
    assert "created_at" in tx
    assert "timestamp" in tx
    assert tx["timestamp"] == tx["created_at"]
