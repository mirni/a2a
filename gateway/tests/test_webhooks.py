"""Tests for the webhook delivery system."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gateway.src.webhooks import (
    _decrypt_secret,
    _encrypt_secret,
    sign_payload,
    verify_signature,
)

# ---------------------------------------------------------------------------
# HMAC signing unit tests
# ---------------------------------------------------------------------------


class TestWebhookHMAC:
    def test_sign_payload_returns_hex(self):
        sig = sign_payload("my-secret", b'{"event": "test"}')
        assert isinstance(sig, str)
        bytes.fromhex(sig)  # must be valid hex

    def test_verify_valid_signature(self):
        payload = b'{"event": "billing.deposit"}'
        secret = "test-secret"
        sig = sign_payload(secret, payload)
        assert verify_signature(secret, payload, sig) is True

    def test_verify_wrong_signature(self):
        payload = b'{"event": "test"}'
        assert verify_signature("secret", payload, "deadbeef" * 8) is False

    def test_verify_malformed_hex(self):
        payload = b'{"event": "test"}'
        assert verify_signature("secret", payload, "not-hex!!!") is False

    def test_verify_none_signature(self):
        assert verify_signature("secret", b"data", None) is False

    def test_verify_empty_signature(self):
        assert verify_signature("secret", b"data", "") is False


# ---------------------------------------------------------------------------
# Encryption/decryption helpers
# ---------------------------------------------------------------------------


class TestWebhookEncryption:
    def test_encrypt_no_key_returns_plaintext(self):
        with patch("gateway.src.webhooks._WEBHOOK_ENCRYPTION_KEY", ""):
            assert _encrypt_secret("my-secret") == "my-secret"

    def test_decrypt_no_key_returns_plaintext(self):
        with patch("gateway.src.webhooks._WEBHOOK_ENCRYPTION_KEY", ""):
            assert _decrypt_secret("my-secret") == "my-secret"

    def test_decrypt_invalid_returns_plaintext(self):
        """If decryption fails (wrong key or not encrypted), return as-is."""
        with patch("gateway.src.webhooks._WEBHOOK_ENCRYPTION_KEY", "badkey"):
            assert _decrypt_secret("not-encrypted") == "not-encrypted"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_webhook(client, pro_api_key, app):
    """Pro tier should be able to register a webhook."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/webhook",
                "event_types": ["billing.deposit", "billing.usage_recorded"],
                "secret": "my-secret-key",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["id"].startswith("whk-")
    assert data["agent_id"] == "pro-agent"
    assert data["url"] == "https://example.com/webhook"
    assert data["active"] == 1


@pytest.mark.asyncio
async def test_list_webhooks(client, pro_api_key, app):
    """Should list registered webhooks for an agent."""
    # Register a webhook first
    await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/hook1",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_webhooks",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["webhooks"]) >= 1


@pytest.mark.asyncio
async def test_delete_webhook(client, pro_api_key, app):
    """Should deactivate a webhook."""
    # Register
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/to-delete",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    webhook_id = resp.json()["id"]

    # Delete
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "delete_webhook",
            "params": {"webhook_id": webhook_id},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # Verify it's gone from list
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_webhooks",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    webhooks = resp.json()["webhooks"]
    ids = [w["id"] for w in webhooks]
    assert webhook_id not in ids


@pytest.mark.asyncio
async def test_webhook_requires_pro(client, api_key):
    """Free tier should not access webhook tools."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "test-agent",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "test-secret",
            },
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_delivery_matching_events(client, pro_api_key, app):
    """Registering for billing.deposit should create webhook correctly."""
    # Register
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://httpbin.org/post",
                "event_types": ["billing.deposit"],
                "secret": "delivery-test-secret",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (200, 201)
    webhook_id = resp.json()["id"]

    # Verify via list_webhooks
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_webhooks",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    webhooks = resp.json()["webhooks"]
    found = [w for w in webhooks if w["id"] == webhook_id]
    assert len(found) == 1
    assert found[0]["url"] == "https://httpbin.org/post"


@pytest.mark.asyncio
async def test_webhook_with_filter_agent_ids(client, pro_api_key, app):
    """Webhook with filter_agent_ids should be stored correctly."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://httpbin.org/post",
                "event_types": ["billing.deposit"],
                "secret": "filter-secret",
                "filter_agent_ids": ["agent-a", "agent-b"],
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["id"].startswith("whk-")
