"""Tests for P2-2: Multi-currency parameter in gateway payment tools.

Verifies that create_intent, create_escrow, create_subscription, and
create_split_intent correctly accept and propagate a ``currency`` parameter
(default: CREDITS) through to the wallet layer.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _fund_usd(ctx, agent_id: str, amount: float) -> None:
    """Deposit USD into an agent's wallet (agent must already have a wallet)."""
    await ctx.tracker.wallet.deposit(agent_id, amount, description="test-usd-seed", currency="USD")


# ---------------------------------------------------------------------------
# create_intent  (tier_required: free)
# ---------------------------------------------------------------------------


class TestCreateIntentCurrency:
    """create_intent should accept an optional currency parameter."""

    async def test_create_intent_default_currency(self, client, app, api_key):
        """create_intent without explicit currency should default to CREDITS."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-ci-default", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {"payer": "test-agent", "payee": "payee-ci-default", "amount": 5.0},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "CREDITS"

    async def test_create_intent_explicit_usd(self, client, app, api_key):
        """create_intent with currency=USD should return USD and use the USD wallet."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-ci-usd", initial_balance=100.0, signup_bonus=False)

        # Fund payer with USD
        await _fund_usd(ctx, "test-agent", 500.0)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "test-agent",
                    "payee": "payee-ci-usd",
                    "amount": 10.0,
                    "currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["currency"] == "USD"

    async def test_create_intent_capture_uses_currency(self, client, app, api_key):
        """Capturing a USD intent should move USD, not CREDITS."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-ci-cap", initial_balance=0.0, signup_bonus=False)
        await _fund_usd(ctx, "test-agent", 500.0)

        # Create USD intent
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "test-agent",
                    "payee": "payee-ci-cap",
                    "amount": 25.0,
                    "currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        intent_id = resp.json()["id"]

        # Check USD balance of payer before capture (should still have 500 USD;
        # intent creation does NOT withdraw yet)
        payer_usd_before = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        assert payer_usd_before == 500.0

        # Capture the intent -- this triggers the wallet transfer
        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "capture_intent",
                "params": {"intent_id": intent_id},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200, f"Capture failed: {resp.text}"

        # After capture, payer USD should be 475 and payee USD should be 25
        payer_usd_after = await ctx.tracker.wallet.get_balance("test-agent", currency="USD")
        payee_usd_after = await ctx.tracker.wallet.get_balance("payee-ci-cap", currency="USD")
        assert payer_usd_after == 475.0
        assert payee_usd_after == 25.0


# ---------------------------------------------------------------------------
# create_escrow  (tier_required: pro)
# ---------------------------------------------------------------------------


class TestCreateEscrowCurrency:
    """create_escrow should accept an optional currency parameter."""

    async def test_create_escrow_explicit_usd(self, client, app, pro_api_key):
        """create_escrow with currency=USD should hold USD funds."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-ce-usd", initial_balance=100.0, signup_bonus=False)
        await _fund_usd(ctx, "pro-agent", 500.0)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_escrow",
                "params": {
                    "payer": "pro-agent",
                    "payee": "payee-ce-usd",
                    "amount": 50.0,
                    "currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "USD"

        # Verify payer USD balance decreased (escrow withdraws immediately)
        payer_usd = await ctx.tracker.wallet.get_balance("pro-agent", currency="USD")
        assert payer_usd == 450.0

    async def test_create_escrow_default_currency(self, client, app, pro_api_key):
        """create_escrow without currency should default to CREDITS."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-ce-def", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_escrow",
                "params": {
                    "payer": "pro-agent",
                    "payee": "payee-ce-def",
                    "amount": 10.0,
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "CREDITS"


# ---------------------------------------------------------------------------
# create_subscription  (tier_required: starter)
# ---------------------------------------------------------------------------


class TestCreateSubscriptionCurrency:
    """create_subscription should accept an optional currency parameter."""

    async def test_create_subscription_default_currency(self, client, app, pro_api_key):
        """create_subscription without currency should default to CREDITS."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-cs-def", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_subscription",
                "params": {
                    "payer": "pro-agent",
                    "payee": "payee-cs-def",
                    "amount": 10.0,
                    "interval": "daily",
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "CREDITS"

    async def test_create_subscription_explicit_usd(self, client, app, pro_api_key):
        """create_subscription with currency=USD should return USD in response."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-cs-usd", initial_balance=100.0, signup_bonus=False)
        await _fund_usd(ctx, "pro-agent", 500.0)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_subscription",
                "params": {
                    "payer": "pro-agent",
                    "payee": "payee-cs-usd",
                    "amount": 10.0,
                    "interval": "daily",
                    "currency": "USD",
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "USD"


# ---------------------------------------------------------------------------
# create_split_intent  (tier_required: pro)
# ---------------------------------------------------------------------------


class TestCreateSplitIntentCurrency:
    """create_split_intent should accept an optional currency parameter."""

    async def test_create_split_intent_default_currency(self, client, app, pro_api_key):
        """create_split_intent without currency defaults to CREDITS."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("split-payee-a", initial_balance=0.0, signup_bonus=False)
        await ctx.tracker.wallet.create("split-payee-b", initial_balance=0.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_split_intent",
                "params": {
                    "payer": "pro-agent",
                    "amount": 100.0,
                    "splits": [
                        {"payee": "split-payee-a", "percentage": 60},
                        {"payee": "split-payee-b", "percentage": 40},
                    ],
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "CREDITS"

    async def test_create_split_intent_explicit_usd(self, client, app, pro_api_key):
        """create_split_intent with currency=USD should move USD funds."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("split-usd-a", initial_balance=0.0, signup_bonus=False)
        await ctx.tracker.wallet.create("split-usd-b", initial_balance=0.0, signup_bonus=False)
        await _fund_usd(ctx, "pro-agent", 500.0)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_split_intent",
                "params": {
                    "payer": "pro-agent",
                    "amount": 100.0,
                    "currency": "USD",
                    "splits": [
                        {"payee": "split-usd-a", "percentage": 70},
                        {"payee": "split-usd-b", "percentage": 30},
                    ],
                },
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["currency"] == "USD"

        # Verify USD balances
        a_usd = await ctx.tracker.wallet.get_balance("split-usd-a", currency="USD")
        b_usd = await ctx.tracker.wallet.get_balance("split-usd-b", currency="USD")
        assert a_usd == 70.0
        assert b_usd == 30.0


# ---------------------------------------------------------------------------
# Invalid currency
# ---------------------------------------------------------------------------


class TestInvalidCurrency:
    """Invalid currency codes should return an error."""

    async def test_create_intent_invalid_currency(self, client, app, api_key):
        """create_intent with an invalid currency should return an error."""
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("payee-inv", initial_balance=100.0, signup_bonus=False)

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "create_intent",
                "params": {
                    "payer": "test-agent",
                    "payee": "payee-inv",
                    "amount": 5.0,
                    "currency": "FAKE_COIN",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should fail with a 400 (validation error)
        assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
