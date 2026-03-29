"""Tests for Stripe Checkout integration (fiat on-ramp).

Covers:
- _verify_stripe_signature: HMAC-SHA256 webhook signature verification
- POST /v1/checkout: authentication, package selection, custom credits, error cases
- POST /v1/stripe-webhook: credit deposit on payment, invalid payloads, signature check
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Signature verification (unit tests — no app needed)
# ---------------------------------------------------------------------------


class TestVerifyStripeSignature:
    """Tests for _verify_stripe_signature()."""

    def _make_signature(self, payload: bytes, secret: str, timestamp: str) -> str:
        """Build a valid Stripe-style v1 signature header."""
        signed_payload = f"{timestamp}.".encode() + payload
        sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return f"t={timestamp},v1={sig}"

    def test_valid_signature_passes(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        payload = b'{"type": "checkout.session.completed"}'
        secret = "whsec_test_secret_123"
        ts = str(int(time.time()))
        header = self._make_signature(payload, secret, ts)

        assert _verify_stripe_signature(payload, header, secret) is True

    def test_wrong_secret_fails(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        payload = b'{"type": "checkout.session.completed"}'
        secret = "whsec_correct"
        ts = str(int(time.time()))
        header = self._make_signature(payload, secret, ts)

        assert _verify_stripe_signature(payload, header, "whsec_wrong") is False

    def test_tampered_payload_fails(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        payload = b'{"type": "checkout.session.completed"}'
        secret = "whsec_test"
        ts = str(int(time.time()))
        header = self._make_signature(payload, secret, ts)

        tampered = b'{"type": "checkout.session.completed", "hacked": true}'
        assert _verify_stripe_signature(tampered, header, secret) is False

    def test_empty_secret_fails(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        assert _verify_stripe_signature(b"payload", "t=123,v1=abc", "") is False

    def test_empty_header_fails(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        assert _verify_stripe_signature(b"payload", "", "whsec_test") is False

    def test_malformed_header_fails(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        assert _verify_stripe_signature(b"payload", "garbage", "whsec_test") is False

    def test_missing_v1_in_header_fails(self):
        from gateway.src.stripe_checkout import _verify_stripe_signature

        assert _verify_stripe_signature(b"payload", "t=123", "whsec_test") is False


# ---------------------------------------------------------------------------
# POST /v1/checkout (integration tests — uses app + mock Stripe API)
# ---------------------------------------------------------------------------


class TestCreateCheckout:
    """Tests for the checkout endpoint."""

    async def test_checkout_requires_auth(self, client):
        resp = await client.post("/v1/checkout", json={"package": "starter"})
        assert resp.status_code == 401

    async def test_checkout_invalid_key(self, client):
        resp = await client.post(
            "/v1/checkout",
            json={"package": "starter"},
            headers={"Authorization": "Bearer ak_invalid_key"},
        )
        assert resp.status_code == 401

    async def test_checkout_unknown_package(self, client, api_key, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")
        resp = await client.post(
            "/v1/checkout",
            json={"package": "nonexistent"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        assert "nonexistent" in resp.json()["error"]["message"]

    async def test_checkout_credits_below_minimum(self, client, api_key, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")
        resp = await client.post(
            "/v1/checkout",
            json={"credits": 50},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400
        assert "minimum 100" in resp.json()["error"]["message"]

    async def test_checkout_no_package_no_credits(self, client, api_key, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")
        resp = await client.post(
            "/v1/checkout",
            json={},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400

    async def test_checkout_missing_stripe_key(self, client, api_key, monkeypatch):
        monkeypatch.delenv("STRIPE_API_KEY", raising=False)
        resp = await client.post(
            "/v1/checkout",
            json={"package": "starter"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 503
        assert "STRIPE_API_KEY" in resp.json()["error"]["message"]

    async def test_checkout_starter_package_calls_stripe(self, client, api_key, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")

        fake_stripe_response = Mock()
        fake_stripe_response.status_code = 200
        fake_stripe_response.json.return_value = {
            "id": "cs_test_abc123",
            "url": "https://checkout.stripe.com/pay/cs_test_abc123",
        }

        with patch("gateway.src.stripe_checkout.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = fake_stripe_response
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            resp = await client.post(
                "/v1/checkout",
                json={"package": "starter"},
                headers={"Authorization": f"Bearer {api_key}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["result"]["credits"] == 1000
        assert body["result"]["amount_usd"] == 10.0
        assert body["result"]["session_id"] == "cs_test_abc123"
        assert "checkout.stripe.com" in body["result"]["checkout_url"]

    async def test_checkout_custom_credits(self, client, api_key, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")

        fake_resp = Mock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "id": "cs_test_custom",
            "url": "https://checkout.stripe.com/pay/cs_test_custom",
        }

        with patch("gateway.src.stripe_checkout.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = fake_resp
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            resp = await client.post(
                "/v1/checkout",
                json={"credits": 2500},
                headers={"Authorization": f"Bearer {api_key}"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["result"]["credits"] == 2500
        assert body["result"]["amount_usd"] == 25.0

    async def test_checkout_stripe_api_error(self, client, api_key, monkeypatch):
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_fake")

        fake_resp = Mock()
        fake_resp.status_code = 400
        fake_resp.text = "Bad request"

        with patch("gateway.src.stripe_checkout.httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = fake_resp
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            resp = await client.post(
                "/v1/checkout",
                json={"package": "starter"},
                headers={"Authorization": f"Bearer {api_key}"},
            )

        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "stripe_error"


# ---------------------------------------------------------------------------
# POST /v1/stripe-webhook (integration tests)
# ---------------------------------------------------------------------------


class TestStripeWebhook:
    """Tests for the webhook handler."""

    _WEBHOOK_SECRET = "whsec_test_secret_for_webhook"

    _session_counter = 0

    def _checkout_completed_event(self, agent_id: str, credits: int, *, session_id: str | None = None) -> dict:
        if session_id is None:
            TestStripeWebhook._session_counter += 1
            session_id = f"cs_test_{TestStripeWebhook._session_counter}"
        return {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "metadata": {
                        "agent_id": agent_id,
                        "credits": str(credits),
                    },
                }
            },
        }

    def _sign_payload(self, payload: bytes, secret: str | None = None) -> str:
        """Generate a valid stripe-signature header for the given payload."""
        s = secret or self._WEBHOOK_SECRET
        ts = str(int(time.time()))
        signed = f"{ts}.".encode() + payload
        sig = hmac.new(s.encode(), signed, hashlib.sha256).hexdigest()
        return f"t={ts},v1={sig}"

    def _signed_headers(self, payload: bytes, secret: str | None = None) -> dict:
        return {
            "Content-Type": "application/json",
            "stripe-signature": self._sign_payload(payload, secret),
        }

    async def test_webhook_deposits_credits(self, client, app, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("webhook-agent", initial_balance=0.0, signup_bonus=False)

        event = self._checkout_completed_event("webhook-agent", 5000)
        payload = json.dumps(event).encode()
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )

        assert resp.status_code == 200
        assert resp.json()["received"] is True

        balance = await ctx.tracker.wallet.get_balance("webhook-agent")
        assert balance == 5000.0

    async def test_webhook_creates_wallet_if_missing(self, client, app, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        event = self._checkout_completed_event("new-webhook-agent", 1000)
        payload = json.dumps(event).encode()
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )

        assert resp.status_code == 200

        ctx = app.state.ctx
        balance = await ctx.tracker.wallet.get_balance("new-webhook-agent")
        assert balance == 1500.0  # 1000 deposit + 500 signup bonus

    async def test_webhook_refuses_without_secret(self, client, monkeypatch):
        """When STRIPE_WEBHOOK_SECRET is not set, refuse all webhooks."""
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        event = {"type": "checkout.session.completed", "data": {"object": {}}}
        resp = await client.post(
            "/v1/stripe-webhook",
            content=json.dumps(event).encode(),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 503
        assert "not configured" in resp.json()["error"]

    async def test_webhook_invalid_json(self, client, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        payload = b"not json at all"
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["error"]

    async def test_webhook_ignores_non_checkout_events(self, client, app, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        event = {"type": "invoice.paid", "data": {"object": {}}}
        payload = json.dumps(event).encode()
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )
        # Should acknowledge but not deposit
        assert resp.status_code == 200
        assert resp.json()["received"] is True

    async def test_webhook_missing_metadata_no_crash(self, client, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_test", "metadata": {}}},
        }
        payload = json.dumps(event).encode()
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )
        assert resp.status_code == 200

    async def test_webhook_rejects_invalid_signature(self, client, monkeypatch):
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_real_secret")
        event = {"type": "checkout.session.completed", "data": {"object": {}}}
        resp = await client.post(
            "/v1/stripe-webhook",
            content=json.dumps(event).encode(),
            headers={
                "Content-Type": "application/json",
                "stripe-signature": "t=123,v1=bad_signature",
            },
        )
        assert resp.status_code == 400
        assert "Invalid signature" in resp.json()["error"]

    async def test_webhook_accepts_valid_signature(self, client, app, monkeypatch):
        secret = "whsec_test_secret_for_webhook"
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)

        await app.state.ctx.tracker.wallet.create("sig-agent", initial_balance=0.0, signup_bonus=False)
        event = self._checkout_completed_event("sig-agent", 500)
        payload = json.dumps(event).encode()

        ts = str(int(time.time()))
        signed = f"{ts}.".encode() + payload
        sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        sig_header = f"t={ts},v1={sig}"

        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "stripe-signature": sig_header,
            },
        )
        assert resp.status_code == 200

        balance = await app.state.ctx.tracker.wallet.get_balance("sig-agent")
        assert balance == 500.0

    async def test_webhook_rejects_excessive_credits(self, client, app, monkeypatch):
        """Credits above 1,000,000 should be rejected."""
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        await app.state.ctx.tracker.wallet.create("greedy-agent", initial_balance=0.0, signup_bonus=False)
        event = self._checkout_completed_event("greedy-agent", 2_000_000)
        payload = json.dumps(event).encode()
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )
        assert resp.status_code == 400
        assert "Credit amount" in resp.json()["error"]

    async def test_webhook_rejects_zero_credits(self, client, app, monkeypatch):
        """Zero credits should be rejected."""
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        event = self._checkout_completed_event("zero-agent", 0)
        payload = json.dumps(event).encode()
        resp = await client.post(
            "/v1/stripe-webhook",
            content=payload,
            headers=self._signed_headers(payload),
        )
        assert resp.status_code == 400

    async def test_webhook_replay_same_session_deposits_only_once(self, client, app, monkeypatch):
        """Replaying the same webhook event (same session id) must not double-deposit."""
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", self._WEBHOOK_SECRET)
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("replay-agent", initial_balance=0.0, signup_bonus=False)

        event = self._checkout_completed_event("replay-agent", 500, session_id="cs_replay_dedup")
        payload = json.dumps(event).encode()
        headers = self._signed_headers(payload)

        # First delivery — should deposit
        resp1 = await client.post("/v1/stripe-webhook", content=payload, headers=headers)
        assert resp1.status_code == 200

        # Second delivery (replay) — should be idempotent
        resp2 = await client.post("/v1/stripe-webhook", content=payload, headers=headers)
        assert resp2.status_code == 200

        # Balance must be 500, NOT 1000
        balance = await ctx.tracker.wallet.get_balance("replay-agent")
        assert balance == 500.0
