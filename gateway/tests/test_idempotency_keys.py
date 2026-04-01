"""Tests for idempotency_key support on financial write tools.

Covers: deposit, withdraw, create_split_intent, create_performance_escrow,
and refund_settlement.  Each tool should accept an optional idempotency_key;
when provided twice, the second call must return the same result without
creating a duplicate side-effect.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _execute(client, api_key: str, tool: str, params: dict, *, idempotency_key: str | None = None):
    """Shorthand for POST /v1/execute."""
    headers = {"Authorization": f"Bearer {api_key}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    resp = await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers=headers,
    )
    return resp


# ---------------------------------------------------------------------------
# deposit idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deposit_idempotency_returns_same_result(client, api_key, app):
    """Calling deposit twice with the same idempotency_key should not double-credit."""
    params = {
        "agent_id": "test-agent",
        "amount": 100.0,
        "description": "top-up",
        "idempotency_key": "dep-idem-001",
    }

    r1 = await _execute(client, api_key, "deposit", params)
    assert r1.status_code == 200
    balance_after_first = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "deposit", params)
    assert r2.status_code == 200
    balance_after_second = r2.json()["new_balance"]

    # The balance should not have increased on the retry
    assert balance_after_second == balance_after_first


@pytest.mark.asyncio
async def test_deposit_without_idempotency_key_creates_separate(client, api_key, app):
    """Two deposits without idempotency_key should each add funds."""
    params = {"agent_id": "test-agent", "amount": 50.0}

    r1 = await _execute(client, api_key, "deposit", params)
    assert r1.status_code == 200
    b1 = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "deposit", params)
    assert r2.status_code == 200
    b2 = r2.json()["new_balance"]

    # Second deposit should increase the balance further
    assert b2 > b1


@pytest.mark.asyncio
async def test_deposit_different_idempotency_keys_create_separate(client, api_key, app):
    """Different idempotency keys should each produce a distinct deposit."""
    params_a = {
        "agent_id": "test-agent",
        "amount": 25.0,
        "idempotency_key": "dep-A",
    }
    params_b = {
        "agent_id": "test-agent",
        "amount": 25.0,
        "idempotency_key": "dep-B",
    }

    r1 = await _execute(client, api_key, "deposit", params_a)
    assert r1.status_code == 200
    b1 = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "deposit", params_b)
    assert r2.status_code == 200
    b2 = r2.json()["new_balance"]

    assert b2 == b1 + 25.0


# ---------------------------------------------------------------------------
# withdraw idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_idempotency_returns_same_result(client, api_key, app):
    """Calling withdraw twice with the same idempotency_key should not double-debit."""
    params = {
        "agent_id": "test-agent",
        "amount": 50.0,
        "description": "fee",
        "idempotency_key": "wd-idem-001",
    }

    r1 = await _execute(client, api_key, "withdraw", params)
    assert r1.status_code == 200
    balance_after_first = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "withdraw", params)
    assert r2.status_code == 200
    balance_after_second = r2.json()["new_balance"]

    assert balance_after_second == balance_after_first


@pytest.mark.asyncio
async def test_withdraw_without_idempotency_key_creates_separate(client, api_key, app):
    """Two withdrawals without idempotency_key should each debit funds."""
    params = {"agent_id": "test-agent", "amount": 10.0}

    r1 = await _execute(client, api_key, "withdraw", params)
    assert r1.status_code == 200
    b1 = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "withdraw", params)
    assert r2.status_code == 200
    b2 = r2.json()["new_balance"]

    assert b2 < b1


# ---------------------------------------------------------------------------
# create_split_intent idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_split_intent_idempotency(client, pro_api_key, app):
    """Same idempotency_key on create_split_intent should not withdraw twice."""
    ctx = app.state.ctx
    # pro_api_key is for "pro-agent" which already has a wallet with 5000 credits
    await ctx.tracker.wallet.create("payee-split-a", initial_balance=0.0, signup_bonus=False)
    await ctx.tracker.wallet.create("payee-split-b", initial_balance=0.0, signup_bonus=False)

    params = {
        "payer": "pro-agent",
        "amount": 100.0,
        "splits": [
            {"payee": "payee-split-a", "percentage": 60},
            {"payee": "payee-split-b", "percentage": 40},
        ],
        "description": "split-test",
        "idempotency_key": "split-idem-001",
    }

    r1 = await _execute(client, pro_api_key, "create_split_intent", params)
    assert r1.status_code in (200, 201), r1.json()

    payer_balance_after_first = await ctx.tracker.wallet.get_balance("pro-agent")

    r2 = await _execute(client, pro_api_key, "create_split_intent", params)
    assert r2.status_code in (200, 201), r2.json()

    payer_balance_after_second = await ctx.tracker.wallet.get_balance("pro-agent")

    # The only balance change should be the gateway per-call fee (if any),
    # NOT another 100-credit split withdrawal.
    balance_drop = payer_balance_after_first - payer_balance_after_second
    assert balance_drop < 100.0, f"Balance dropped by {balance_drop}, suggesting the split was executed twice"
    # Results should match
    assert r1.json()["status"] == r2.json()["status"]


# ---------------------------------------------------------------------------
# create_performance_escrow idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_performance_escrow_idempotency(client, pro_api_key, app):
    """Same idempotency_key on create_performance_escrow should not create two escrows."""
    ctx = app.state.ctx
    # pro_api_key is for "pro-agent" which already has 5000 credits
    await ctx.tracker.wallet.create("perf-payee", initial_balance=0.0, signup_bonus=False)

    params = {
        "payer": "pro-agent",
        "payee": "perf-payee",
        "amount": 200.0,
        "metric_name": "sharpe_30d",
        "threshold": 2.0,
        "description": "perf-gate-test",
        "idempotency_key": "perf-idem-001",
    }

    r1 = await _execute(client, pro_api_key, "create_performance_escrow", params)
    assert r1.status_code in (200, 201), r1.json()

    r2 = await _execute(client, pro_api_key, "create_performance_escrow", params)
    assert r2.status_code in (200, 201), r2.json()

    # Same escrow_id must be returned
    assert r1.json()["escrow_id"] == r2.json()["escrow_id"]

    # Payer balance should reflect only ONE escrow withdrawal (200 credits)
    # plus any per-call gateway fees, but NOT two 200-credit escrow withdrawals
    balance = await ctx.tracker.wallet.get_balance("pro-agent")
    # With only one 200-credit escrow hold, balance must be above 4700
    # (allowing generous margin for gateway fees)
    assert balance > 4700.0, f"Balance {balance} suggests escrow was created twice"


# ---------------------------------------------------------------------------
# refund_settlement idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refund_settlement_idempotency(client, pro_api_key, app):
    """Same idempotency_key on refund_settlement should not double-refund."""
    ctx = app.state.ctx
    # pro_api_key is for "pro-agent" which already has 5000 credits
    await ctx.tracker.wallet.create("refund-payee", initial_balance=5000.0, signup_bonus=False)

    # Create and capture an intent to get a settlement
    intent = await ctx.payment_engine.create_intent(
        payer="pro-agent",
        payee="refund-payee",
        amount=500.0,
        description="test-intent",
    )
    settlement = await ctx.payment_engine.capture(intent.id)

    params = {
        "settlement_id": settlement.id,
        "amount": 200.0,
        "reason": "customer request",
        "idempotency_key": "refund-idem-001",
    }

    r1 = await _execute(client, pro_api_key, "refund_settlement", params)
    assert r1.status_code == 200, r1.json()

    r2 = await _execute(client, pro_api_key, "refund_settlement", params)
    assert r2.status_code == 200, r2.json()

    # Same refund id
    assert r1.json()["id"] == r2.json()["id"]
    # Amount should match
    assert r1.json()["amount"] == r2.json()["amount"]


# ---------------------------------------------------------------------------
# Idempotency-Key HTTP header (T5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_key_header_prevents_duplicate(client, api_key, app):
    """Idempotency-Key as HTTP header prevents duplicate deposits."""
    params = {"agent_id": "test-agent", "amount": 100.0, "description": "header-test"}

    r1 = await _execute(client, api_key, "deposit", params, idempotency_key="hdr-idem-001")
    assert r1.status_code == 200
    b1 = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "deposit", params, idempotency_key="hdr-idem-001")
    assert r2.status_code == 200
    b2 = r2.json()["new_balance"]

    assert b1 == b2, "Duplicate request with same Idempotency-Key header should not double-credit"


@pytest.mark.asyncio
async def test_idempotency_key_header_different_keys_create_separate(client, api_key, app):
    """Different Idempotency-Key headers should each produce a distinct deposit."""
    params = {"agent_id": "test-agent", "amount": 25.0}

    r1 = await _execute(client, api_key, "deposit", params, idempotency_key="hdr-A")
    assert r1.status_code == 200
    b1 = r1.json()["new_balance"]

    r2 = await _execute(client, api_key, "deposit", params, idempotency_key="hdr-B")
    assert r2.status_code == 200
    b2 = r2.json()["new_balance"]

    assert b2 == b1 + 25.0
