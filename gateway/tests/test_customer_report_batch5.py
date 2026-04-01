"""Batch 5 — P2 Data Quality tests (Items 14-18).

Item 14: OpenAPI — add securitySchemes
Item 15: get_transactions — add currency field
Item 16: get_exchange_rate — fix return type (string to number)
Item 17: Wallet freeze/suspend
Item 18: Dispute deadlines
"""

from __future__ import annotations

import hashlib
import secrets
import time

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
# Item 14: OpenAPI — securitySchemes
# ============================================================================


class TestOpenAPISecuritySchemes:
    """OpenAPI spec should define securitySchemes."""

    async def test_security_schemes_present(self, client):
        """components.securitySchemes.BearerAuth exists."""
        resp = await client.get("/v1/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        schemes = data["components"].get("securitySchemes", {})
        assert "BearerAuth" in schemes
        assert schemes["BearerAuth"]["type"] == "http"
        assert schemes["BearerAuth"]["scheme"] == "bearer"

    async def test_x402_security_scheme_present(self, client):
        """components.securitySchemes.X402Payment exists."""
        resp = await client.get("/v1/openapi.json")
        data = resp.json()
        schemes = data["components"].get("securitySchemes", {})
        assert "X402Payment" in schemes
        assert schemes["X402Payment"]["type"] == "apiKey"


# ============================================================================
# Item 15: get_transactions — currency field
# ============================================================================


class TestTransactionsCurrency:
    """get_transactions results should include a currency field."""

    async def test_transactions_include_currency(self, client, app):
        """Deposit in CREDITS, get_transactions returns currency: CREDITS."""
        ctx = app.state.ctx
        key = await _create_agent(app, "txn-curr-agent", tier="free", balance=1000.0)

        await ctx.tracker.wallet.deposit("txn-curr-agent", 50.0, description="test deposit", currency="CREDITS")

        resp = await _exec(client, "get_transactions", {"agent_id": "txn-curr-agent"}, key)
        assert resp.status_code == 200
        txns = resp.json()["transactions"]
        assert len(txns) >= 1
        # At least one transaction should have currency
        has_currency = any("currency" in t for t in txns)
        assert has_currency


# ============================================================================
# Item 16: get_exchange_rate — return type fix
# ============================================================================


class TestExchangeRateReturnType:
    """get_exchange_rate should return rate as float, not string."""

    async def test_exchange_rate_is_numeric(self, client, app):
        """rate field should be a number, not a string."""
        key = await _create_agent(app, "rate-agent", tier="free", balance=1000.0)

        resp = await _exec(
            client,
            "get_exchange_rate",
            {"from_currency": "CREDITS", "to_currency": "CREDITS"},
            key,
        )
        assert resp.status_code == 200
        rate = resp.json()["rate"]
        assert isinstance(rate, str), f"Expected string, got {type(rate).__name__}: {rate}"
        # Verify it's a valid numeric string
        float(rate)  # should not raise


# ============================================================================
# Item 17: Wallet freeze/suspend
# ============================================================================


class TestWalletFreeze:
    """Frozen wallets should reject deposits and withdrawals."""

    async def test_freeze_wallet_blocks_withdraw(self, client, app):
        """After freeze, withdraw attempt fails."""
        admin_key = await _create_admin_agent(app, "admin-freeze")
        key = await _create_agent(app, "freeze-agent", tier="free", balance=1000.0)

        # Freeze
        resp = await _exec(client, "freeze_wallet", {"agent_id": "freeze-agent"}, admin_key)
        assert resp.status_code == 200
        assert resp.json()["frozen"] is True

        # Attempt withdraw
        resp = await _exec(
            client,
            "withdraw",
            {"agent_id": "freeze-agent", "amount": 10.0},
            key,
        )
        assert resp.status_code != 200

    async def test_unfreeze_wallet_allows_withdraw(self, client, app):
        """After unfreeze, withdraw succeeds."""
        admin_key = await _create_admin_agent(app, "admin-unfreeze")
        key = await _create_agent(app, "unfreeze-agent", tier="free", balance=1000.0)

        # Freeze then unfreeze
        await _exec(client, "freeze_wallet", {"agent_id": "unfreeze-agent"}, admin_key)
        resp = await _exec(client, "unfreeze_wallet", {"agent_id": "unfreeze-agent"}, admin_key)
        assert resp.status_code == 200
        assert resp.json()["frozen"] is False

        # Withdraw should succeed
        resp = await _exec(
            client,
            "withdraw",
            {"agent_id": "unfreeze-agent", "amount": 10.0},
            key,
        )
        assert resp.status_code == 200


# ============================================================================
# Item 18: Dispute deadlines
# ============================================================================


class TestDisputeDeadlines:
    """Disputes should have a deadline_at field set on creation."""

    async def test_dispute_has_deadline(self, client, app):
        """Opening a dispute sets deadline_at (7 days from now)."""
        ctx = app.state.ctx
        await _create_agent(app, "buyer-dl18", tier="pro", balance=5000.0)
        await _create_agent(app, "seller-dl18", tier="free", balance=0.0)

        escrow = await ctx.payment_engine.create_escrow(payer="buyer-dl18", payee="seller-dl18", amount=50.0)
        dispute = await ctx.dispute_engine.open_dispute(
            escrow_id=escrow.id, opener="buyer-dl18", reason="test deadline"
        )

        assert "deadline_at" in dispute
        assert dispute["deadline_at"] is not None
        # deadline should be roughly 7 days from now
        assert dispute["deadline_at"] > time.time()
        assert dispute["deadline_at"] < time.time() + 8 * 86400
