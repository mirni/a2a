"""RACE1.1 regression — concurrent deposits must all succeed.

The v1.2.9 audit found that 0/5 concurrent deposit requests succeed under
load due to unhandled SQLite lock contention.  This test fires 5 concurrent
deposits via asyncio.gather and asserts every one returns HTTP 200 with the
correct final balance.
"""

from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.asyncio


async def test_concurrent_deposits_all_succeed(client, api_key):
    """Fire 5 concurrent deposits and verify all succeed."""
    agent_id = "test-agent"
    deposit_amount = "10.00"
    num_deposits = 5

    async def _deposit():
        return await client.post(
            f"/v1/billing/wallets/{agent_id}/deposit",
            json={"amount": deposit_amount},
            headers={"Authorization": f"Bearer {api_key}"},
        )

    responses = await asyncio.gather(*[_deposit() for _ in range(num_deposits)])

    # Every deposit must succeed
    for i, resp in enumerate(responses):
        assert resp.status_code == 200, f"Deposit {i} failed with {resp.status_code}: {resp.text}"

    # Final balance = initial 1000 + 5 * 10 = 1050
    balance_resp = await client.get(
        f"/v1/billing/wallets/{agent_id}/balance",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert balance_resp.status_code == 200
    bal = balance_resp.json()["balance"]
    # Balance may be str or float depending on serialization
    assert float(bal) == 1050.0


async def test_concurrent_deposits_transaction_records(client, api_key):
    """Verify each concurrent deposit creates a transaction record."""
    agent_id = "test-agent"

    async def _deposit():
        return await client.post(
            f"/v1/billing/wallets/{agent_id}/deposit",
            json={"amount": "5.00"},
            headers={"Authorization": f"Bearer {api_key}"},
        )

    responses = await asyncio.gather(*[_deposit() for _ in range(3)])
    for resp in responses:
        assert resp.status_code == 200

    txns_resp = await client.get(
        f"/v1/billing/wallets/{agent_id}/transactions",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert txns_resp.status_code == 200
    txns = txns_resp.json()["transactions"]
    deposit_txns = [t for t in txns if t["tx_type"] == "deposit"]
    assert len(deposit_txns) >= 3


async def test_deposit_nonexistent_wallet_returns_error(client, app):
    """Deposit to a wallet that does not exist should return 404, not 500."""
    ctx = app.state.ctx
    # Create a key but no wallet
    key_info = await ctx.key_manager.create_key("ghost-agent", tier="free")
    key = key_info["key"]

    resp = await client.post(
        "/v1/billing/wallets/ghost-agent/deposit",
        json={"amount": "10.00"},
        headers={"Authorization": f"Bearer {key}"},
    )
    # Should be a handled error (404 wallet_not_found), not 500
    assert resp.status_code != 500, f"Got unhandled 500: {resp.text}"
    assert resp.status_code in (404, 400, 402)
