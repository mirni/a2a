"""Tests for x402 settlement events, usage recording, and failure handling."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_proof_dict(
    *,
    to: str = "0xTestMerchant",
    value: str = "1000000",
    valid_before: int | None = None,
    nonce: str | None = None,
) -> dict:
    if valid_before is None:
        valid_before = int(time.time()) + 600
    if nonce is None:
        nonce = "0x" + "dd" * 32
    return {
        "x402_version": 1,
        "scheme": "exact",
        "network": "base",
        "payload": {
            "signature": "0x" + "ff" * 65,
            "authorization": {
                "from": "0xPayerWallet",
                "to": to,
                "value": value,
                "valid_after": 0,
                "valid_before": valid_before,
                "nonce": nonce,
            },
        },
    }


def _encode_proof(proof_dict: dict) -> str:
    return base64.b64encode(json.dumps(proof_dict).encode()).decode()


@pytest.fixture
async def x402_app(tmp_data_dir, monkeypatch):
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

    application = create_app()
    ctx_manager = lifespan(application)
    await ctx_manager.__aenter__()
    yield application
    await ctx_manager.__aexit__(None, None, None)


@pytest.fixture
async def x402_client(x402_app):
    import httpx

    transport = httpx.ASGITransport(app=x402_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _mock_facilitator():
    """Return a context manager that mocks the facilitator for both verify and settle."""
    verify_resp = MagicMock()
    verify_resp.status_code = 200
    verify_resp.json.return_value = {"valid": True}

    settle_resp = MagicMock()
    settle_resp.status_code = 200
    settle_resp.json.return_value = {"settled": True}
    settle_resp.raise_for_status = lambda: None

    def _pick_response(*args, **kwargs):
        url = args[0] if args else kwargs.get("url", "")
        if "settle" in str(url):
            return settle_resp
        return verify_resp

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=_pick_response)

    return patch("gateway.src.x402.httpx.AsyncClient", return_value=mock_client), mock_client


class TestUsageRecording:
    @pytest.mark.asyncio
    async def test_usage_recorded_with_wallet_address(self, x402_client, x402_app):
        """Usage is recorded with the payer wallet as agent_id."""
        proof = _make_proof_dict(nonce="0x" + "e1" * 32)
        encoded = _encode_proof(proof)

        patcher, mock_client = _mock_facilitator()
        with patcher:
            ctx = x402_app.state.ctx
            await ctx.tracker.wallet.create("0xPayerWallet", initial_balance=0.0, signup_bonus=False)

            resp = await x402_client.post(
                "/v1/execute",
                json={"tool": "get_balance", "params": {"agent_id": "0xPayerWallet"}},
                headers={"X-PAYMENT": encoded},
            )

        assert resp.status_code == 200

        # Check usage was recorded
        db = ctx.tracker.storage.db
        cursor = await db.execute(
            "SELECT agent_id, function FROM usage_records WHERE agent_id = ?",
            ("0xPayerWallet",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "0xPayerWallet"
        assert row[1] == "get_balance"


class TestEventPublishing:
    @pytest.mark.asyncio
    async def test_settlement_event_published(self, x402_client, x402_app):
        """x402.payment_settled event is published after tool execution."""
        nonce = "0x" + "e2" * 32
        proof = _make_proof_dict(nonce=nonce)
        encoded = _encode_proof(proof)

        patcher, mock_client = _mock_facilitator()
        with patcher:
            ctx = x402_app.state.ctx
            await ctx.tracker.wallet.create("0xPayerWallet", initial_balance=0.0, signup_bonus=False)

            resp = await x402_client.post(
                "/v1/execute",
                json={"tool": "get_balance", "params": {"agent_id": "0xPayerWallet"}},
                headers={"X-PAYMENT": encoded},
            )

        assert resp.status_code == 200

        # Check event was published
        db = ctx.event_bus.db
        cursor = await db.execute("SELECT event_type, payload FROM events WHERE event_type = 'x402.payment_settled'")
        row = await cursor.fetchone()
        assert row is not None
        payload = json.loads(row[1])
        assert payload["nonce"] == nonce
        assert payload["payer"] == "0xPayerWallet"


class TestSettlementRetryQueue:
    @pytest.mark.asyncio
    async def test_failed_settlement_queued_for_retry(self, x402_client, x402_app):
        """When settlement fails, the proof should be queued for retry."""
        proof = _make_proof_dict(nonce="0x" + "f1" * 32)
        encoded = _encode_proof(proof)

        # Mock verify to succeed but settle to fail
        verify_resp = MagicMock()
        verify_resp.status_code = 200
        verify_resp.json.return_value = {"valid": True}

        settle_resp = MagicMock()
        settle_resp.status_code = 500
        settle_resp.raise_for_status.side_effect = Exception("Settlement failed")

        def _pick_response(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "settle" in str(url):
                return settle_resp
            return verify_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_pick_response)

        with patch("gateway.src.x402.httpx.AsyncClient", return_value=mock_client):
            ctx = x402_app.state.ctx
            await ctx.tracker.wallet.create("0xPayerWallet", initial_balance=0.0, signup_bonus=False)

            resp = await x402_client.post(
                "/v1/execute",
                json={"tool": "get_balance", "params": {"agent_id": "0xPayerWallet"}},
                headers={"X-PAYMENT": encoded},
            )

        assert resp.status_code == 200
        # The failed settlement should be queued
        verifier = x402_app.state.ctx.x402_verifier
        assert len(verifier.pending_settlements) == 1
        queued = verifier.pending_settlements[0]
        assert queued.payload.authorization.nonce == "0x" + "f1" * 32

    @pytest.mark.asyncio
    async def test_retry_settles_pending(self, x402_app):
        """retry_pending_settlements() should attempt settlement again."""
        from gateway.src.x402 import X402PaymentProof

        verifier = x402_app.state.ctx.x402_verifier
        proof_dict = _make_proof_dict(nonce="0x" + "f2" * 32)
        proof = X402PaymentProof.model_validate(proof_dict)

        # Manually queue a failed settlement
        verifier.queue_failed_settlement(proof)
        assert len(verifier.pending_settlements) == 1

        # Mock facilitator to succeed on retry
        settle_resp = MagicMock()
        settle_resp.status_code = 200
        settle_resp.json.return_value = {"settled": True}
        settle_resp.raise_for_status = lambda: None

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=settle_resp)

        with patch("gateway.src.x402.httpx.AsyncClient", return_value=mock_client):
            settled, failed = await verifier.retry_pending_settlements()

        assert settled == 1
        assert failed == 0
        assert len(verifier.pending_settlements) == 0


class TestFacilitatorTimeout:
    @pytest.mark.asyncio
    async def test_facilitator_verify_timeout_returns_error(self, x402_client, x402_app):
        """If the facilitator /verify call times out, return a 402 error."""
        proof = _make_proof_dict(nonce="0x" + "f3" * 32)
        encoded = _encode_proof(proof)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("Connection timed out"))

        with patch("gateway.src.x402.httpx.AsyncClient", return_value=mock_client):
            ctx = x402_app.state.ctx
            await ctx.tracker.wallet.create("0xPayerWallet", initial_balance=0.0, signup_bonus=False)

            resp = await x402_client.post(
                "/v1/execute",
                json={"tool": "get_balance", "params": {"agent_id": "0xPayerWallet"}},
                headers={"X-PAYMENT": encoded},
            )

        assert resp.status_code == 402
        assert resp.json()["type"].endswith("/payment-verification-failed")


class TestFreeTool:
    @pytest.mark.asyncio
    async def test_free_tool_with_x402_costs_zero(self, x402_client, x402_app):
        """A free tool (per_call=0) should work via x402 with value=0."""
        proof = _make_proof_dict(nonce="0x" + "f4" * 32, value="0")
        encoded = _encode_proof(proof)

        patcher, mock_client = _mock_facilitator()
        with patcher:
            ctx = x402_app.state.ctx
            await ctx.tracker.wallet.create("0xPayerWallet", initial_balance=0.0, signup_bonus=False)

            resp = await x402_client.post(
                "/v1/execute",
                json={"tool": "get_balance", "params": {"agent_id": "0xPayerWallet"}},
                headers={"X-PAYMENT": encoded},
            )

        assert resp.status_code == 200
        assert float(resp.headers["x-charged"]) == 0.0


class TestSettlementFailureHandling:
    @pytest.mark.asyncio
    async def test_settlement_failure_does_not_break_response(self, x402_client, x402_app):
        """If settlement fails, the response should still be 200."""
        proof = _make_proof_dict(nonce="0x" + "e3" * 32)
        encoded = _encode_proof(proof)

        # Mock verify to succeed but settle to fail
        verify_resp = MagicMock()
        verify_resp.status_code = 200
        verify_resp.json.return_value = {"valid": True}

        settle_resp = MagicMock()
        settle_resp.status_code = 500
        settle_resp.raise_for_status.side_effect = Exception("Settlement failed")

        def _pick_response(*args, **kwargs):
            url = args[0] if args else kwargs.get("url", "")
            if "settle" in str(url):
                return settle_resp
            return verify_resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_pick_response)

        with patch("gateway.src.x402.httpx.AsyncClient", return_value=mock_client):
            ctx = x402_app.state.ctx
            await ctx.tracker.wallet.create("0xPayerWallet", initial_balance=0.0, signup_bonus=False)

            resp = await x402_client.post(
                "/v1/execute",
                json={"tool": "get_balance", "params": {"agent_id": "0xPayerWallet"}},
                headers={"X-PAYMENT": encoded},
            )

        # Response should still succeed despite settlement failure
        assert resp.status_code == 200
