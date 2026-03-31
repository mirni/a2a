"""Tests for HMAC webhook delivery verification.

Verifies that webhook payloads are signed with HMAC-SHA256 and that
signatures can be correctly verified using shared secrets.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper: compute expected HMAC-SHA256 signature
# ---------------------------------------------------------------------------

def _compute_expected_signature(secret: str, payload_bytes: bytes) -> str:
    """Compute the HMAC-SHA256 hex digest that the webhook system should produce."""
    return hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Unit tests for sign_payload / verify_signature helpers
# ---------------------------------------------------------------------------


class TestSignPayload:
    """Tests for the sign_payload function."""

    async def test_sign_payload_returns_hex_string(self):
        """sign_payload should return a hex-encoded HMAC-SHA256 digest."""
        from gateway.src.webhooks import sign_payload

        secret = "test-secret"
        payload = b'{"type": "billing.deposit"}'
        sig = sign_payload(secret, payload)

        # SHA-256 hex digest is 64 chars long
        assert isinstance(sig, str)
        assert len(sig) == 64
        # Must be valid hex
        int(sig, 16)

    async def test_sign_payload_uses_sha256(self):
        """sign_payload must use HMAC-SHA256 (not SHA-3 or other variants)."""
        from gateway.src.webhooks import sign_payload

        secret = "my-secret"
        payload = b'{"event": "test"}'
        sig = sign_payload(secret, payload)

        expected = hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        assert sig == expected

    async def test_sign_payload_deterministic(self):
        """Same inputs must always produce the same signature."""
        from gateway.src.webhooks import sign_payload

        secret = "deterministic-secret"
        payload = b'{"count": 42}'
        sig1 = sign_payload(secret, payload)
        sig2 = sign_payload(secret, payload)
        assert sig1 == sig2


class TestVerifySignature:
    """Tests for the verify_signature function."""

    async def test_valid_signature_accepted(self):
        """verify_signature should return True for a correctly signed payload."""
        from gateway.src.webhooks import sign_payload, verify_signature

        secret = "verify-secret"
        payload = b'{"type": "billing.deposit", "amount": "100.00"}'
        sig = sign_payload(secret, payload)

        assert verify_signature(secret, payload, sig) is True

    async def test_tampered_payload_rejected(self):
        """Altering the payload after signing must cause verification to fail."""
        from gateway.src.webhooks import sign_payload, verify_signature

        secret = "tamper-secret"
        original_payload = b'{"amount": "100.00"}'
        sig = sign_payload(secret, original_payload)

        tampered_payload = b'{"amount": "999.99"}'
        assert verify_signature(secret, tampered_payload, sig) is False

    async def test_wrong_secret_rejected(self):
        """Verifying with a different secret must fail."""
        from gateway.src.webhooks import sign_payload, verify_signature

        payload = b'{"type": "test"}'
        sig = sign_payload("secret-A", payload)

        assert verify_signature("secret-B", payload, sig) is False

    async def test_empty_signature_rejected(self):
        """An empty signature string must be rejected."""
        from gateway.src.webhooks import verify_signature

        assert verify_signature("secret", b"payload", "") is False

    async def test_none_signature_rejected(self):
        """A None signature must be rejected (missing header scenario)."""
        from gateway.src.webhooks import verify_signature

        assert verify_signature("secret", b"payload", None) is False

    async def test_malformed_signature_rejected(self):
        """A non-hex signature must be rejected gracefully."""
        from gateway.src.webhooks import verify_signature

        assert verify_signature("secret", b"payload", "not-a-hex-string!!") is False

    async def test_uses_timing_safe_comparison(self):
        """verify_signature must use hmac.compare_digest for timing safety."""
        import unittest.mock as mock

        from gateway.src.webhooks import sign_payload, verify_signature

        secret = "timing-secret"
        payload = b'{"safe": true}'
        sig = sign_payload(secret, payload)

        with mock.patch("hmac.compare_digest", wraps=hmac.compare_digest) as mock_cmp:
            verify_signature(secret, payload, sig)
            mock_cmp.assert_called_once()


class TestDifferentSecretsProduceDifferentSignatures:
    """Different secrets must produce different HMAC signatures."""

    async def test_different_secrets_different_signatures(self):
        """Two distinct secrets signing the same payload must yield different sigs."""
        from gateway.src.webhooks import sign_payload

        payload = b'{"type": "billing.deposit"}'
        sig_a = sign_payload("secret-alpha", payload)
        sig_b = sign_payload("secret-beta", payload)

        assert sig_a != sig_b


# ---------------------------------------------------------------------------
# Integration test: _send method includes correct header
# ---------------------------------------------------------------------------


class TestWebhookDeliverySigning:
    """Verify that the WebhookManager._send method signs payloads correctly."""

    async def test_delivery_includes_hmac_signature_header(self, tmp_path):
        """The POST request from _send must include X-A2A-Signature header."""
        import unittest.mock as mock

        from gateway.src.webhooks import WebhookManager, sign_payload

        db_path = str(tmp_path / "wh.db")
        mgr = WebhookManager(dsn=f"sqlite:///{db_path}")

        # We need to mock out the database and HTTP parts
        # but verify the signature computation
        secret = "integration-secret"
        event = {"type": "billing.deposit", "amount": "50.00"}
        payload_bytes = json.dumps(event).encode()
        expected_sig = sign_payload(secret, payload_bytes)

        captured_headers: dict = {}

        class FakeResponse:
            status_code = 200
            text = "OK"

        class FakeClient:
            async def post(self, url, *, content, headers):
                captured_headers.update(headers)
                return FakeResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        webhook = {
            "id": "whk-test123",
            "agent_id": "test-agent",
            "url": "https://example.com/hook",
            "event_types": ["billing.deposit"],
            "secret": secret,
            "active": 1,
        }

        # Set up a real database with schema
        await mgr.connect()
        try:
            # Insert webhook record first (foreign key requirement)
            await mgr._require_db().execute(
                """INSERT INTO webhooks
                   (id, agent_id, url, event_types, secret, created_at, active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (
                    webhook["id"],
                    webhook["agent_id"],
                    webhook["url"],
                    json.dumps(webhook["event_types"]),
                    webhook["secret"],
                    1000.0,
                ),
            )
            await mgr._require_db().commit()

            # Now insert the delivery record
            delivery_id = await mgr._insert_delivery(
                webhook_id=webhook["id"],
                event_type="billing.deposit",
                payload_json=json.dumps(event),
                now=1000.0,
            )

            with mock.patch("httpx.AsyncClient", return_value=FakeClient()):
                await mgr._send(webhook, delivery_id, event)
        finally:
            await mgr.close()

        assert "X-A2A-Signature" in captured_headers
        assert captured_headers["X-A2A-Signature"] == expected_sig

    async def test_delivery_signature_is_sha256_not_sha3(self, tmp_path):
        """The delivery signature MUST use SHA-256, NOT SHA-3-256."""
        import unittest.mock as mock

        from gateway.src.webhooks import WebhookManager

        db_path = str(tmp_path / "wh.db")
        mgr = WebhookManager(dsn=f"sqlite:///{db_path}")

        secret = "sha256-check-secret"
        event = {"type": "test.event"}
        payload_bytes = json.dumps(event).encode()

        # Compute what SHA-256 and SHA-3-256 would produce
        sha256_sig = hmac.new(
            secret.encode(), payload_bytes, hashlib.sha256
        ).hexdigest()
        sha3_sig = hmac.new(
            secret.encode(), payload_bytes, hashlib.sha3_256
        ).hexdigest()

        captured_sig = {}

        class FakeResponse:
            status_code = 200
            text = "OK"

        class FakeClient:
            async def post(self, url, *, content, headers):
                captured_sig["sig"] = headers.get("X-A2A-Signature")
                return FakeResponse()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        webhook = {
            "id": "whk-sha256check",
            "agent_id": "test-agent",
            "url": "https://example.com/hook",
            "event_types": ["test.event"],
            "secret": secret,
            "active": 1,
        }

        await mgr.connect()
        try:
            await mgr._require_db().execute(
                """INSERT INTO webhooks
                   (id, agent_id, url, event_types, secret, created_at, active)
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (
                    webhook["id"],
                    webhook["agent_id"],
                    webhook["url"],
                    json.dumps(webhook["event_types"]),
                    webhook["secret"],
                    1000.0,
                ),
            )
            await mgr._require_db().commit()

            delivery_id = await mgr._insert_delivery(
                webhook_id=webhook["id"],
                event_type="test.event",
                payload_json=json.dumps(event),
                now=1000.0,
            )

            with mock.patch("httpx.AsyncClient", return_value=FakeClient()):
                await mgr._send(webhook, delivery_id, event)
        finally:
            await mgr.close()

        actual_sig = captured_sig["sig"]
        assert actual_sig == sha256_sig, (
            f"Expected SHA-256 signature but got something else. "
            f"SHA-256={sha256_sig}, SHA-3-256={sha3_sig}, actual={actual_sig}"
        )
        assert actual_sig != sha3_sig or sha256_sig == sha3_sig  # sanity
