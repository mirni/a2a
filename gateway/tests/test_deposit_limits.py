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

    async def test_enterprise_tier_deposit_within_limit(self, client, app):
        """Enterprise-tier agent can deposit up to the enterprise cap."""
        key = await _create_agent(app, "ent-dep", "enterprise", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/ent-dep/deposit",
            json={"amount": "10000000.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200, resp.text

    async def test_enterprise_tier_deposit_exceeds_limit(self, client, app):
        """Enterprise-tier agent cannot deposit above the enterprise cap.

        v1.2.4 audit P0-6: before this fix, ``deposit_limits`` had no
        enterprise entry so ``.get("enterprise")`` returned ``None``
        and the cap check was silently skipped for enterprise callers.
        The default is now 10,000,000 credits (policy placeholder —
        subject to human review in PR).
        """
        key = await _create_agent(app, "ent-over", "enterprise", balance=0)
        resp = await client.post(
            "/v1/billing/wallets/ent-over/deposit",
            json={"amount": "10000001.00"},
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 403, resp.text
        data = resp.json()
        assert "limit" in str(data).lower()

    async def test_admin_bypasses_deposit_limits(self, client, app, admin_api_key):
        """Admin-scoped keys bypass the per-tier deposit cap entirely.

        The ``admin_api_key`` fixture creates a pro-tier key with the
        ``admin`` scope. ``authenticate()`` promotes this to
        ``agent_tier == "admin"`` and the deposit_limits lookup
        returns ``None`` (no ``admin`` key in the dict), so the cap
        check is bypassed. Depositing 100M (10× the enterprise cap)
        must still succeed.
        """
        resp = await client.post(
            "/v1/billing/wallets/admin-agent/deposit",
            json={"amount": "100000000.00"},
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200, resp.text
