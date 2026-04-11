"""Regression tests for audit findings C2/C3/C4 (payments atomicity).

These tests assert the fundamental invariant of a payments system:
**money in = money out**. The payer's balance after refund must equal
its balance before capture (modulo documented fees).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _ensure_wallet(ctx, agent_id: str, balance: float = 500.0) -> None:
    try:
        await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    except Exception:
        pass


async def _create_intent(client, api_key, payer: str, payee: str, amount: float) -> str:
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_intent",
            "params": {"payer": payer, "payee": payee, "amount": amount, "description": "audit c4"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def test_capture_refund_round_trip_restores_payer_balance(client, api_key, app):
    """Audit C4 + v1.2.4 HIGH-2: capture then refund returns customer whole.

    v1.2.4 (audit v1.2.3 HIGH-2 / ADR-012, supersedes ADR-011): a full refund
    restores the intent amount **and** credits the gateway fee back to the
    payer. A round-trip create→capture→refund is balance-neutral.

    Prior bug (C4): refund returned 200 voided without moving funds.
    Prior bug (H-REF): refund double-credited the gateway fee.
    """
    ctx = app.state.ctx
    await _ensure_wallet(ctx, "c4-payee", 0.0)

    # Measure balance BEFORE create_intent — a full refund must restore it.
    payer_before = await ctx.tracker.get_balance("test-agent")
    payee_before = await ctx.tracker.get_balance("c4-payee")

    intent_id = await _create_intent(client, api_key, "test-agent", "c4-payee", 25.0)

    capture_resp = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert capture_resp.status_code == 200, capture_resp.text

    refund_resp = await client.post(
        "/v1/execute",
        json={"tool": "refund_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert refund_resp.status_code == 200, refund_resp.text
    assert refund_resp.json()["status"] == "refunded"

    payer_after = await ctx.tracker.get_balance("test-agent")
    payee_after = await ctx.tracker.get_balance("c4-payee")

    # v1.2.4: full refund returns the customer whole — including the fee.
    assert payer_after == payer_before
    assert payee_after == payee_before


async def test_double_capture_returns_409_and_no_double_debit(client, api_key, app):
    """Audit C3: second capture on same intent must return 409, not double-debit."""
    ctx = app.state.ctx
    await _ensure_wallet(ctx, "c3-payee", 0.0)

    intent_id = await _create_intent(client, api_key, "test-agent", "c3-payee", 7.5)

    first = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert first.status_code == 200, first.text

    payer_after_first = await ctx.tracker.get_balance("test-agent")

    # Second capture: must return 409 invalid_state, not error out or re-debit
    second = await client.post(
        "/v1/execute",
        json={"tool": "capture_intent", "params": {"intent_id": intent_id}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert second.status_code == 409, second.text

    # Payer balance must be unchanged (no double-debit)
    assert await ctx.tracker.get_balance("test-agent") == payer_after_first
