"""Regression tests for v1.3.1 multi-persona audit findings.

Covers:
  SEC.8  — XSS in description fields (HTML tag stripping)
  SEC.7  — SQL-ish payer/agent_id rejected
  P4.4   — Crypto amounts with 8 decimal places accepted
  P5.2   — /livez and /readyz Kubernetes probes
  P5.7   — SSE heartbeat within 8 seconds
"""

from __future__ import annotations

import pytest

from gateway.src.routes.sse import SSEConfig
from gateway.src.validators import sanitize_text

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_agent(app, agent_id: str, tier: str = "free", balance: float = 5000.0) -> str:
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


# ---------------------------------------------------------------------------
# SEC.8 — XSS sanitization
# ---------------------------------------------------------------------------


class TestXSSSanitization:
    """HTML tags must be stripped from user-provided text fields."""

    def test_sanitize_text_strips_tags(self):
        """Unit test: sanitize_text removes HTML tags, preserves text."""
        result = sanitize_text('<script>alert("xss")</script>Pay me')
        assert "<script>" not in result
        assert 'alert("xss")' in result
        assert "Pay me" in result

    def test_sanitize_text_preserves_normal(self):
        """Unit test: sanitize_text preserves normal text."""
        assert sanitize_text("Data analysis service") == "Data analysis service"

    async def test_xss_tags_stripped_via_model(self, client, app):
        """Integration: XSS payload accepted but tags stripped in model."""
        from gateway.src.routes.v1.payments import CreateIntentRequest

        model = CreateIntentRequest(
            payer="agent-alice",
            payee="agent-bob",
            amount="10.00",
            description='<script>alert("xss")</script>Pay me',
        )
        assert "<script>" not in model.description
        assert 'alert("xss")' in model.description
        assert "Pay me" in model.description

    async def test_xss_request_accepted(self, client, app):
        """Integration: request with XSS payload returns 201 (not 422)."""
        key = await _create_agent(app, "xss-payer")
        await _create_agent(app, "xss-payee")
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "xss-payer",
                "payee": "xss-payee",
                "amount": "10.00",
                "description": '<script>alert("xss")</script>Pay me',
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 201

    async def test_description_normal_text_ok(self, client, app):
        key = await _create_agent(app, "normal-payer")
        await _create_agent(app, "normal-payee")
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "normal-payer",
                "payee": "normal-payee",
                "amount": "10.00",
                "description": "Data analysis service",
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# SEC.7 — Agent ID format validation
# ---------------------------------------------------------------------------


class TestAgentIdValidation:
    """SQL-ish and special-char agent IDs must be rejected at 422."""

    async def test_sql_payer_rejected(self, client, app):
        key = await _create_agent(app, "legit-payer")
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "'; DROP TABLE wallets; --",
                "payee": "legit-payer",
                "amount": "10.00",
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 422

    async def test_valid_agent_id_accepted(self, client, app):
        key = await _create_agent(app, "valid-payer")
        await _create_agent(app, "valid-payee")
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "valid-payer",
                "payee": "valid-payee",
                "amount": "10.00",
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# P4.4/P4.5 — Crypto decimal precision
# ---------------------------------------------------------------------------


class TestCryptoDecimalPrecision:
    """Amount fields must accept up to 8 decimal places for crypto."""

    async def test_crypto_amount_8_decimals(self, client, app):
        key = await _create_agent(app, "crypto-payer")
        await _create_agent(app, "crypto-payee")
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "crypto-payer",
                "payee": "crypto-payee",
                "amount": "0.00012500",
                "currency": "ETH",
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 201

    async def test_fiat_amount_2_decimals(self, client, app):
        key = await _create_agent(app, "fiat-payer")
        await _create_agent(app, "fiat-payee")
        resp = await client.post(
            "/v1/payments/intents",
            json={
                "payer": "fiat-payer",
                "payee": "fiat-payee",
                "amount": "10.00",
                "currency": "CREDITS",
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 201


# ---------------------------------------------------------------------------
# P5.2 — Kubernetes liveness / readiness probes
# ---------------------------------------------------------------------------


class TestHealthProbes:
    """GET /livez and /readyz must return 200."""

    async def test_livez(self, client):
        resp = await client.get("/livez")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_readyz(self, client):
        resp = await client.get("/readyz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# P5.7 — SSE heartbeat within 8 seconds
# ---------------------------------------------------------------------------


class TestSSEHeartbeat:
    """The default heartbeat interval must fire within 8 seconds."""

    async def test_sse_heartbeat_within_8s(self, app):
        """Verify SSEConfig default heartbeat is <= 8s."""
        config = SSEConfig()
        assert config.heartbeat_interval_seconds <= 8.0, (
            f"Default heartbeat {config.heartbeat_interval_seconds}s exceeds 8s window"
        )
