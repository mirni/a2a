"""Batch 4 — P1 Missing Tools tests (Items 12-13).

Item 12: get_intent and get_escrow — expose as tools
Item 13: Idempotency keys for create_escrow and create_subscription
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _exec(client, tool, params, key):
    return await client.post(
        "/v1/execute",
        json={"tool": tool, "params": params},
        headers={"Authorization": f"Bearer {key}"},
    )


# ============================================================================
# Item 12: get_intent and get_escrow — expose as tools
# ============================================================================


class TestGetIntentTool:
    """get_intent should return intent details when called as a tool."""

    async def test_get_intent_returns_details(self, client, app):
        """Create intent, then query it with get_intent tool."""
        ctx = app.state.ctx
        key = await _create_agent(app, "payer-gi12", tier="free", balance=5000.0)
        await _create_agent(app, "payee-gi12", tier="free", balance=0.0)

        intent = await ctx.payment_engine.create_intent(
            payer="payer-gi12", payee="payee-gi12", amount=25.0, description="test intent"
        )

        resp = await _exec(client, "get_intent", {"intent_id": intent.id}, key)
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["id"] == intent.id
        assert result["status"] == "pending"
        assert result["payer"] == "payer-gi12"
        assert result["payee"] == "payee-gi12"
        assert float(result["amount"]) == 25.0

    async def test_get_intent_not_found(self, client, app):
        """get_intent with nonexistent ID returns 404."""
        key = await _create_agent(app, "agent-gi12b", tier="free", balance=1000.0)
        resp = await _exec(client, "get_intent", {"intent_id": "nonexistent"}, key)
        assert resp.status_code == 404


class TestGetEscrowTool:
    """get_escrow should return escrow details when called as a tool."""

    async def test_get_escrow_returns_details(self, client, app):
        """Create escrow, then query it with get_escrow tool."""
        ctx = app.state.ctx
        key = await _create_agent(app, "payer-ge12", tier="pro", balance=5000.0)
        await _create_agent(app, "payee-ge12", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="payer-ge12", payee="payee-ge12", amount=50.0)

        resp = await _exec(client, "get_escrow", {"escrow_id": escrow.id}, key)
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["id"] == escrow.id
        assert result["status"] == "held"
        assert float(result["amount"]) == 50.0

    async def test_get_escrow_not_found(self, client, app):
        """get_escrow with nonexistent ID returns 404."""
        key = await _create_agent(app, "agent-ge12b", tier="free", balance=1000.0)
        resp = await _exec(client, "get_escrow", {"escrow_id": "nonexistent"}, key)
        assert resp.status_code == 404


# ============================================================================
# Item 13: Idempotency keys for create_escrow and create_subscription
# ============================================================================


class TestEscrowIdempotency:
    """create_escrow with idempotency_key should return same escrow on retry."""

    async def test_create_escrow_idempotency_same_key(self, client, app):
        """Two create_escrow calls with same idempotency_key return same escrow."""
        key = await _create_agent(app, "idemp-payer-e", tier="pro", balance=10000.0)
        await _create_agent(app, "idemp-payee-e", tier="free", balance=0.0)

        params = {
            "payer": "idemp-payer-e",
            "payee": "idemp-payee-e",
            "amount": 100.0,
            "idempotency_key": "escrow-key-1",
        }

        resp1 = await _exec(client, "create_escrow", params, key)
        assert resp1.status_code == 200
        id1 = resp1.json()["result"]["id"]

        resp2 = await _exec(client, "create_escrow", params, key)
        assert resp2.status_code == 200
        id2 = resp2.json()["result"]["id"]

        assert id1 == id2

    async def test_create_escrow_different_key(self, client, app):
        """Two create_escrow calls with different keys return different escrows."""
        key = await _create_agent(app, "idemp-payer-e2", tier="pro", balance=10000.0)
        await _create_agent(app, "idemp-payee-e2", tier="free", balance=0.0)

        resp1 = await _exec(
            client,
            "create_escrow",
            {
                "payer": "idemp-payer-e2",
                "payee": "idemp-payee-e2",
                "amount": 50.0,
                "idempotency_key": "escrow-key-a",
            },
            key,
        )
        resp2 = await _exec(
            client,
            "create_escrow",
            {
                "payer": "idemp-payer-e2",
                "payee": "idemp-payee-e2",
                "amount": 50.0,
                "idempotency_key": "escrow-key-b",
            },
            key,
        )
        assert resp1.json()["result"]["id"] != resp2.json()["result"]["id"]


class TestSubscriptionIdempotency:
    """create_subscription with idempotency_key should return same subscription on retry."""

    async def test_create_subscription_idempotency_same_key(self, client, app):
        """Two create_subscription calls with same idempotency_key return same sub."""
        key = await _create_agent(app, "idemp-payer-s", tier="starter", balance=10000.0)
        await _create_agent(app, "idemp-payee-s", tier="free", balance=0.0)

        params = {
            "payer": "idemp-payer-s",
            "payee": "idemp-payee-s",
            "amount": 10.0,
            "interval": "monthly",
            "idempotency_key": "sub-key-1",
        }

        resp1 = await _exec(client, "create_subscription", params, key)
        assert resp1.status_code == 200
        id1 = resp1.json()["result"]["id"]

        resp2 = await _exec(client, "create_subscription", params, key)
        assert resp2.status_code == 200
        id2 = resp2.json()["result"]["id"]

        assert id1 == id2
