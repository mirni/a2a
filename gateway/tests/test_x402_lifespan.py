"""Tests for x402 lifespan wiring — verifier creation and nonce table."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_x402_verifier_none_when_disabled(app):
    """With default env (x402 disabled), verifier should be None."""
    ctx = app.state.ctx
    assert ctx.x402_verifier is None


@pytest.mark.asyncio
async def test_x402_verifier_created_when_enabled(tmp_data_dir, monkeypatch):
    """When X402_ENABLED=true and address set, verifier is created."""
    monkeypatch.setenv("A2A_DATA_DIR", tmp_data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{tmp_data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{tmp_data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{tmp_data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{tmp_data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{tmp_data_dir}/trust.db")
    monkeypatch.setenv("IDENTITY_DSN", f"sqlite:///{tmp_data_dir}/identity.db")
    monkeypatch.setenv("EVENT_BUS_DSN", f"sqlite:///{tmp_data_dir}/event_bus.db")
    monkeypatch.setenv("WEBHOOK_DSN", f"sqlite:///{tmp_data_dir}/webhooks.db")
    monkeypatch.setenv("DISPUTE_DSN", f"sqlite:///{tmp_data_dir}/disputes.db")
    monkeypatch.setenv("MESSAGING_DSN", f"sqlite:///{tmp_data_dir}/messaging.db")
    monkeypatch.setenv("X402_ENABLED", "true")
    monkeypatch.setenv("X402_MERCHANT_ADDRESS", "0xTestMerchant")

    from gateway.src.app import create_app
    from gateway.src.lifespan import lifespan
    from gateway.src.x402 import X402Verifier

    application = create_app()
    ctx_manager = lifespan(application)
    await ctx_manager.__aenter__()
    try:
        ctx = application.state.ctx
        assert ctx.x402_verifier is not None
        assert isinstance(ctx.x402_verifier, X402Verifier)
    finally:
        await ctx_manager.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_x402_nonces_table_exists(app):
    """The x402_nonces table should be created during lifespan startup."""
    ctx = app.state.ctx
    db = ctx.tracker.storage.db
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='x402_nonces'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "x402_nonces"
