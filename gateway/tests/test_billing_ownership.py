"""Tests for P2 #19: Missing check_ownership in billing routes.

get_volume_discount, estimate_cost, convert_currency must enforce ownership.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 5000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


class TestBillingOwnership:
    """Billing routes must enforce ownership via check_ownership."""

    async def test_volume_discount_cross_agent_forbidden(self, client, app):
        """Agent alice cannot query volume discount for agent bob."""
        key = await _create_agent(app, "alice-own")
        await _create_agent(app, "bob-own")

        resp = await client.get(
            "/v1/billing/discounts",
            params={"agent_id": "bob-own", "tool_name": "get_balance", "quantity": "1"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_volume_discount_own_agent_allowed(self, client, app):
        """Agent can query their own volume discount."""
        key = await _create_agent(app, "vd-self")

        resp = await client.get(
            "/v1/billing/discounts",
            params={"agent_id": "vd-self", "tool_name": "get_balance", "quantity": "1"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_convert_currency_cross_agent_forbidden(self, client, app):
        """Agent alice cannot convert currency for agent bob."""
        key = await _create_agent(app, "alice-conv")
        await _create_agent(app, "bob-conv")

        resp = await client.post(
            "/v1/billing/wallets/bob-conv/convert",
            json={"amount": "10.00", "from_currency": "CREDITS", "to_currency": "USD"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403
