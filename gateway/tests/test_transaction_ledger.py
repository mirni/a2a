"""Tests for P1-10: Transaction ledger via get_transactions tool."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_get_transactions_returns_list(client, api_key):
    """Agent transactions are returned as a list (wallet creation may add initial tx)."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_transactions", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert isinstance(body["result"]["transactions"], list)


async def test_get_transactions_after_deposit(client, api_key, app):
    """After recording a transaction, it appears in the ledger."""
    ctx = app.state.ctx

    # Get baseline count
    baseline_resp = await client.post(
        "/v1/execute",
        json={"tool": "get_transactions", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    baseline_count = len(baseline_resp.json()["result"]["transactions"])

    # Record a transaction directly
    await ctx.tracker.storage.record_transaction(
        agent_id="test-agent",
        amount=50.0,
        tx_type="deposit",
        description="Test deposit",
    )

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_transactions", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    txns = body["result"]["transactions"]
    assert len(txns) == baseline_count + 1
    # Most recent transaction is first (ordered by created_at DESC)
    assert txns[0]["tx_type"] == "deposit"
    assert txns[0]["amount"] == 50.0
    assert txns[0]["description"] == "Test deposit"
    assert "created_at" in txns[0]


async def test_get_transactions_respects_limit(client, api_key, app):
    """The limit parameter caps the returned transactions."""
    ctx = app.state.ctx
    for i in range(5):
        await ctx.tracker.storage.record_transaction(
            agent_id="test-agent",
            amount=float(i + 1),
            tx_type="deposit",
            description=f"tx {i}",
        )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_transactions",
            "params": {"agent_id": "test-agent", "limit": 3},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    txns = resp.json()["result"]["transactions"]
    # Limit should cap at 3 regardless of how many exist
    assert len(txns) == 3


async def test_get_transactions_respects_offset(client, api_key, app):
    """The offset parameter skips transactions."""
    ctx = app.state.ctx
    # Get baseline count first
    baseline_resp = await client.post(
        "/v1/execute",
        json={"tool": "get_transactions", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    baseline_count = len(baseline_resp.json()["result"]["transactions"])

    for i in range(5):
        await ctx.tracker.storage.record_transaction(
            agent_id="test-agent",
            amount=float(i + 1),
            tx_type="withdrawal",
            description=f"tx {i}",
        )

    total = baseline_count + 5
    offset = 3
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_transactions",
            "params": {"agent_id": "test-agent", "limit": 100, "offset": offset},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    txns = resp.json()["result"]["transactions"]
    assert len(txns) == total - offset


async def test_get_transactions_free_tier(client, api_key):
    """Free-tier keys can access get_transactions."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_transactions", "params": {"agent_id": "test-agent"}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


async def test_get_transactions_missing_agent_id(client, api_key):
    """Missing agent_id returns 400."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_transactions", "params": {}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "missing_parameter"
