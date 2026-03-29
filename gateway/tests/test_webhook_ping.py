"""Tests for P2-15: Webhook Test/Ping tool (test_webhook)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestWebhookPing:
    """Tests for the test_webhook tool."""

    async def test_tool_exists_in_catalog(self, client, api_key):
        """test_webhook should be in the catalog."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "test_webhook", "params": {"webhook_id": "whk-fake123"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        data = resp.json()
        assert data.get("error", {}).get("code") != "unknown_tool"

    async def test_ping_registered_webhook(self, client, api_key, app):
        """Should send a test.ping event to a registered webhook and return delivery result."""
        ctx = app.state.ctx

        # Register a webhook
        wh = await ctx.webhook_manager.register(
            agent_id="test-agent",
            url="https://example.com/webhook",
            event_types=["test.ping"],
            secret="test-secret",
        )
        webhook_id = wh["id"]

        resp = await client.post(
            "/v1/execute",
            json={"tool": "test_webhook", "params": {"webhook_id": webhook_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        result = data["result"]
        assert "delivery_id" in result
        assert "status" in result
        # response_code may be None if the HTTP request failed (test env),
        # but the delivery record should exist
        assert result["status"] in ("delivered", "pending", "failed")

    async def test_ping_nonexistent_webhook(self, client, api_key):
        """Should return an error or not-found for a nonexistent webhook."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "test_webhook", "params": {"webhook_id": "whk-doesnotexist"}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        # Should indicate the webhook was not found
        data = resp.json()
        # Either a 404 error or a success=True with found=False/error field
        assert resp.status_code in (200, 404)
        if resp.status_code == 200:
            result = data.get("result", {})
            assert result.get("error") or result.get("found") is False or "not found" in str(result).lower()

    async def test_missing_webhook_id_param(self, client, api_key):
        """Should fail when webhook_id param is missing."""
        resp = await client.post(
            "/v1/execute",
            json={"tool": "test_webhook", "params": {}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 400

    async def test_ping_creates_delivery_record(self, client, api_key, app):
        """The ping should create a delivery record in the webhook deliveries table."""
        ctx = app.state.ctx

        wh = await ctx.webhook_manager.register(
            agent_id="test-agent",
            url="https://example.com/webhook-record",
            event_types=["test.ping"],
            secret="s3cret",
        )
        webhook_id = wh["id"]

        resp = await client.post(
            "/v1/execute",
            json={"tool": "test_webhook", "params": {"webhook_id": webhook_id}},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        resp.json()["result"]

        # Verify delivery record exists
        deliveries = await ctx.webhook_manager.get_delivery_history(webhook_id)
        assert len(deliveries) >= 1
        latest = deliveries[0]
        assert latest["event_type"] == "test.ping"
