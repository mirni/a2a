"""Tests for P0 #1: Per-tier deposit limits.

Free-tier agents should not be able to deposit more than 1,000 credits.
Starter: 10,000, Pro: 100,000, Enterprise: 1,000,000,000.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 1000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


class TestPerTierDepositLimits:
    """Deposit amounts must respect per-tier limits."""

    async def test_free_tier_deposit_within_limit(self, client, app):
        """Free-tier agent can deposit up to 1,000."""
        key = await _create_agent(app, "free-dep", "free", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/free-dep/deposit",
            json={"amount": "1000.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_free_tier_deposit_exceeds_limit(self, client, app):
        """Free-tier agent cannot deposit more than 1,000."""
        key = await _create_agent(app, "free-over", "free", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/free-over/deposit",
            json={"amount": "1001.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "limit" in data.get("detail", "").lower() or "limit" in str(data).lower()

    async def test_starter_tier_deposit_within_limit(self, client, app):
        """Starter-tier agent can deposit up to 10,000."""
        key = await _create_agent(app, "starter-dep", "starter", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/starter-dep/deposit",
            json={"amount": "10000.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_starter_tier_deposit_exceeds_limit(self, client, app):
        """Starter-tier agent cannot deposit more than 10,000."""
        key = await _create_agent(app, "starter-over", "starter", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/starter-over/deposit",
            json={"amount": "10001.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403

    async def test_pro_tier_deposit_within_limit(self, client, app):
        """Pro-tier agent can deposit up to 100,000."""
        key = await _create_agent(app, "pro-dep", "pro", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/pro-dep/deposit",
            json={"amount": "100000.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_pro_tier_deposit_exceeds_limit(self, client, app):
        """Pro-tier agent cannot deposit more than 100,000."""
        key = await _create_agent(app, "pro-over", "pro", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/pro-over/deposit",
            json={"amount": "100001.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403
