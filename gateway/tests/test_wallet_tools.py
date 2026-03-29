"""Tests for wallet creation and withdraw gateway tools (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_wallet_via_gateway(client, api_key):
    """Any agent can create a wallet for a new agent_id."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_wallet",
            "params": {"agent_id": "new-agent-123"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["agent_id"] == "new-agent-123"
    assert result["balance"] == 0.0


async def test_create_wallet_with_initial_balance(client, pro_api_key):
    """Wallet can be created with initial balance."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_wallet",
            "params": {"agent_id": "funded-agent", "initial_balance": 500.0},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["balance"] == 500.0


async def test_create_wallet_duplicate(client, api_key):
    """Creating a wallet for an existing agent fails."""
    # test-agent already has a wallet from the api_key fixture
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_wallet",
            "params": {"agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # ValueError from wallet.create → should map to 400 or 409
    assert resp.status_code in (400, 409, 500)


async def test_withdraw_via_gateway(client, api_key):
    """Agent can withdraw credits from wallet."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "withdraw",
            "params": {
                "agent_id": "test-agent",
                "amount": 100.0,
                "description": "Payout request",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["new_balance"] == 900.0  # started with 1000


async def test_withdraw_insufficient_balance(client, api_key):
    """Withdraw more than balance fails."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "withdraw",
            "params": {"agent_id": "test-agent", "amount": 99999.0},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 402
