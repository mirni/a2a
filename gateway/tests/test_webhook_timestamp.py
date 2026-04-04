"""Tests for P1 #5: Stripe webhook timestamp validation.

Webhooks with stale timestamps (|now - t| > 300s) must be rejected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

pytestmark = pytest.mark.asyncio


def _build_signed_webhook(payload: dict, secret: str, timestamp: float | None = None) -> tuple[bytes, str]:
    """Build a Stripe-signed webhook payload and signature header."""
    ts = int(timestamp or time.time())
    body = json.dumps(payload).encode()
    signed_payload = f"{ts}.".encode() + body
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    header = f"t={ts},v1={sig}"
    return body, header


class TestWebhookTimestampValidation:
    """Stripe webhooks with expired timestamps must be rejected."""

    async def test_stale_timestamp_rejected(self, client, app, monkeypatch):
        """Webhook signed 600s ago should be rejected."""
        secret = "whsec_test_secret"
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)

        stale_ts = time.time() - 600  # 10 minutes old
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_stale_test",
                    "metadata": {"agent_id": "stale-agent", "credits": "100"},
                }
            },
        }
        body, sig_header = _build_signed_webhook(payload, secret, timestamp=stale_ts)

        resp = await client.post(
            "/v1/stripe-webhook",
            content=body,
            headers={"stripe-signature": sig_header, "content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json().get("error", "").lower()

    async def test_fresh_timestamp_accepted(self, client, app, monkeypatch):
        """Webhook signed just now should pass timestamp check."""
        secret = "whsec_test_secret"
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)

        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_fresh_test",
                    "metadata": {"agent_id": "fresh-agent", "credits": "100"},
                }
            },
        }
        body, sig_header = _build_signed_webhook(payload, secret)

        # Create wallet so deposit works
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("fresh-agent", initial_balance=0, signup_bonus=False)

        resp = await client.post(
            "/v1/stripe-webhook",
            content=body,
            headers={"stripe-signature": sig_header, "content-type": "application/json"},
        )
        # Should be 200 (accepted) — not 400 from timestamp
        assert resp.status_code == 200

    async def test_future_timestamp_rejected(self, client, app, monkeypatch):
        """Webhook with timestamp 600s in the future should be rejected."""
        secret = "whsec_test_secret"
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)

        future_ts = time.time() + 600
        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_future_test",
                    "metadata": {"agent_id": "future-agent", "credits": "100"},
                }
            },
        }
        body, sig_header = _build_signed_webhook(payload, secret, timestamp=future_ts)

        resp = await client.post(
            "/v1/stripe-webhook",
            content=body,
            headers={"stripe-signature": sig_header, "content-type": "application/json"},
        )
        assert resp.status_code == 400
