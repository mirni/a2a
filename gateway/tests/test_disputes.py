"""Tests for dispute resolution engine (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_open_dispute(client, pro_api_key, app):
    """Open a dispute on an escrow."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("disputer", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("disputed-party", initial_balance=0.0, signup_bonus=False)
    disputer_key = await ctx.key_manager.create_key("disputer", tier="pro")

    # Create escrow first
    escrow = await ctx.payment_engine.create_escrow(payer="disputer", payee="disputed-party", amount=100.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "open_dispute",
            "params": {
                "escrow_id": escrow.id,
                "opener": "disputer",
                "reason": "Service not delivered as promised",
            },
        },
        headers={"Authorization": f"Bearer {disputer_key['key']}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "open"
    assert "id" in result
    assert result["escrow_id"] == escrow.id


async def test_respond_to_dispute(client, pro_api_key, app):
    """Respondent can reply to an open dispute."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("buyer-d", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("seller-d", initial_balance=0.0, signup_bonus=False)
    seller_key = await ctx.key_manager.create_key("seller-d", tier="pro")

    escrow = await ctx.payment_engine.create_escrow(payer="buyer-d", payee="seller-d", amount=50.0)

    # Open dispute
    dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-d", reason="Did not deliver")

    # Seller responds
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "respond_to_dispute",
            "params": {
                "dispute_id": dispute["id"],
                "respondent": "seller-d",
                "response": "Service was delivered on time, see logs",
            },
        },
        headers={"Authorization": f"Bearer {seller_key['key']}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "responded"


async def test_resolve_dispute_refund(client, pro_api_key, app):
    """Admin can resolve a dispute with refund."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("buyer-e", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("seller-e", initial_balance=0.0, signup_bonus=False)

    escrow = await ctx.payment_engine.create_escrow(payer="buyer-e", payee="seller-e", amount=75.0)

    dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-e", reason="Quality issue")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "resolve_dispute",
            "params": {
                "dispute_id": dispute["id"],
                "resolution": "refund",
                "resolved_by": "platform",
                "notes": "Service quality did not meet SLA",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "resolved"
    assert result["resolution"] == "refund"

    # Buyer should get refund
    buyer_balance = await ctx.tracker.wallet.get_balance("buyer-e")
    assert buyer_balance == 1000.0  # original 1000 - 75 (escrow) + 75 (refund)


async def test_resolve_dispute_release(client, pro_api_key, app):
    """Admin can resolve a dispute by releasing funds to payee."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("buyer-f", initial_balance=1000.0, signup_bonus=False)
    await ctx.tracker.wallet.create("seller-f", initial_balance=0.0, signup_bonus=False)

    escrow = await ctx.payment_engine.create_escrow(payer="buyer-f", payee="seller-f", amount=60.0)

    dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-f", reason="Dispute test")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "resolve_dispute",
            "params": {
                "dispute_id": dispute["id"],
                "resolution": "release",
                "resolved_by": "platform",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["resolution"] == "release"

    # Seller should receive funds
    seller_balance = await ctx.tracker.wallet.get_balance("seller-f")
    assert seller_balance == 60.0
