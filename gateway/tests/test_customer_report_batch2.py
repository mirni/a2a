"""Batch 2 — P1 Authorization Hardening tests (Items 6-8).

Item 6: respond_to_dispute — verify caller is actual respondent
Item 7: OWNERSHIP_FIELDS — add opener and initiator (already done in Batch 1)
Item 8: get_dispute and list_disputes — expose as tools
"""

from __future__ import annotations

import hashlib
import secrets

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _create_admin_agent(app, agent_id: str = "admin-agent") -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=10000.0, signup_bonus=False)
    raw_key = f"a2a_admin_{secrets.token_hex(12)}"
    key_hash = hashlib.sha3_256(raw_key.encode()).hexdigest()
    await ctx.paywall_storage.store_key(key_hash=key_hash, agent_id=agent_id, tier="admin")
    return raw_key


async def _exec(client, tool, params, key):
    return await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {key}"},
    )


# ============================================================================
# Item 6: respond_to_dispute — verify caller is actual respondent
# ============================================================================


class TestRespondToDisputeCallerCheck:
    """respond_to_dispute must verify the caller is the actual dispute respondent."""

    async def test_non_respondent_cannot_respond(self, client, app):
        """Agent C (not the respondent) cannot respond to a dispute."""
        ctx = app.state.ctx
        await _create_agent(app, "buyer-b2-6", tier="pro", balance=5000.0)
        await _create_agent(app, "seller-b2-6", tier="pro", balance=0.0)
        key_c = await _create_agent(app, "outsider-b2-6", tier="pro", balance=1000.0)

        escrow = await ctx.payment_engine.create_escrow(payer="buyer-b2-6", payee="seller-b2-6", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-b2-6", reason="test")

        # Agent C (outsider) tries to respond
        resp = await _exec(
            client,
            "respond_to_dispute",
            {
                "dispute_id": dispute["id"],
                "respondent": "outsider-b2-6",
                "response": "I'm not the respondent",
            },
            key_c,
        )
        assert resp.status_code == 403

    async def test_actual_respondent_can_respond(self, client, app):
        """The actual respondent (seller-d) can respond to the dispute."""
        ctx = app.state.ctx
        await _create_agent(app, "buyer-b2-6b", tier="pro", balance=5000.0)
        key_seller = await _create_agent(app, "seller-b2-6b", tier="pro", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="buyer-b2-6b", payee="seller-b2-6b", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-b2-6b", reason="test")

        resp = await _exec(
            client,
            "respond_to_dispute",
            {
                "dispute_id": dispute["id"],
                "respondent": "seller-b2-6b",
                "response": "I am the actual respondent",
            },
            key_seller,
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "responded"


# ============================================================================
# Item 7: OWNERSHIP_FIELDS — opener and initiator
# ============================================================================


class TestOwnershipFieldsExtended:
    """opener and initiator params must be checked against caller agent_id."""

    async def test_opener_mismatch_is_forbidden(self, client, app):
        """Agent A cannot open_dispute with opener set to agent B."""
        ctx = app.state.ctx
        key_a = await _create_agent(app, "opener-check-a", tier="pro", balance=5000.0)
        await _create_agent(app, "opener-check-b", tier="pro", balance=5000.0)
        await _create_agent(app, "payee-opener-check", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="opener-check-b", payee="payee-opener-check", amount=50.0)

        resp = await _exec(
            client,
            "open_dispute",
            {
                "escrow_id": escrow.id,
                "opener": "opener-check-b",
                "reason": "fake opener",
            },
            key_a,
        )
        assert resp.status_code == 403


# ============================================================================
# Item 8: get_dispute and list_disputes — expose as tools
# ============================================================================


class TestDisputeQueryTools:
    """get_dispute and list_disputes should be accessible as tools."""

    async def test_get_dispute_returns_details(self, client, app):
        """get_dispute tool returns dispute details."""
        ctx = app.state.ctx
        key = await _create_agent(app, "buyer-gd8", tier="pro", balance=5000.0)
        await _create_agent(app, "seller-gd8", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="buyer-gd8", payee="seller-gd8", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(
            escrow_id=escrow.id, opener="buyer-gd8", reason="test get_dispute"
        )

        resp = await _exec(client, "get_dispute", {"dispute_id": dispute["id"]}, key)
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["id"] == dispute["id"]
        assert result["status"] == "open"
        assert result["escrow_id"] == escrow.id

    async def test_get_dispute_not_found(self, client, app):
        """get_dispute with bad ID returns 404."""
        key = await _create_agent(app, "buyer-gd8b", tier="pro", balance=5000.0)
        resp = await _exec(client, "get_dispute", {"dispute_id": "nonexistent"}, key)
        assert resp.status_code == 404

    async def test_list_disputes_returns_filtered_list(self, client, app):
        """list_disputes returns disputes for an agent."""
        ctx = app.state.ctx
        key = await _create_agent(app, "buyer-ld8", tier="pro", balance=5000.0)
        await _create_agent(app, "seller-ld8", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="buyer-ld8", payee="seller-ld8", amount=50.0)
        await ctx.dispute_engine.open_dispute(escrow_id=escrow.id, opener="buyer-ld8", reason="test list")

        resp = await _exec(client, "list_disputes", {"agent_id": "buyer-ld8"}, key)
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert "disputes" in result
        assert len(result["disputes"]) >= 1
