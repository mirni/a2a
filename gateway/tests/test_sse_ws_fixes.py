"""Tests for SSE and WebSocket security/compatibility fixes.

Covers:
  P0: SSE endpoint rejects invalid API keys with 401 JSON (not a stream)
  P0: WebSocket Cloudflare-compatible upgrade headers
  P2: WebSocket API key in query params logs warning, header auth supported
"""

from __future__ import annotations

import json
import logging

import pytest
from starlette.testclient import TestClient

from gateway.src.app import create_app

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers for sync WebSocket tests (same pattern as test_websocket.py)
# ---------------------------------------------------------------------------


async def _create_api_key(app_state, agent_id: str = "fix-agent", tier: str = "free") -> str:
    """Create an API key (async helper, run via portal.call)."""
    ctx = app_state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_app_client(tmp_path, monkeypatch):
    """Provide a sync TestClient for WebSocket tests."""
    data_dir = str(tmp_path)
    monkeypatch.setenv("A2A_DATA_DIR", data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")
    monkeypatch.setenv("IDENTITY_DSN", f"sqlite:///{data_dir}/identity.db")
    monkeypatch.setenv("EVENT_BUS_DSN", f"sqlite:///{data_dir}/event_bus.db")
    monkeypatch.setenv("WEBHOOK_DSN", f"sqlite:///{data_dir}/webhooks.db")
    monkeypatch.setenv("DISPUTE_DSN", f"sqlite:///{data_dir}/disputes.db")
    monkeypatch.setenv("MESSAGING_DSN", f"sqlite:///{data_dir}/messaging.db")

    application = create_app()
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


# =========================================================================
# P0: SSE endpoint must reject invalid API keys with 401 JSON
# =========================================================================


class TestSSEInvalidKeyReturns401:
    """SSE endpoint should return 401 JSON — NOT open a stream — for bad keys."""

    async def test_sse_invalid_key_returns_401_status(self, client):
        """SSE with a completely invalid key returns HTTP 401."""
        resp = await client.get(
            "/v1/events/stream",
            headers={"Authorization": "Bearer a2a_bad_totally_invalid_key"},
        )
        assert resp.status_code == 401

    async def test_sse_invalid_key_returns_json_body(self, client):
        """SSE with invalid key returns JSON error body, not an event stream."""
        resp = await client.get(
            "/v1/events/stream",
            headers={"Authorization": "Bearer a2a_bad_totally_invalid_key"},
        )
        body = resp.json()
        assert body["type"].endswith("/invalid-key")

    async def test_sse_invalid_key_content_type_is_problem_json(self, client):
        """SSE with invalid key returns application/problem+json, not text/event-stream."""
        resp = await client.get(
            "/v1/events/stream",
            headers={"Authorization": "Bearer a2a_bad_totally_invalid_key"},
        )
        content_type = resp.headers.get("content-type", "")
        assert "application/problem+json" in content_type
        assert "text/event-stream" not in content_type

    async def test_sse_no_key_returns_401(self, client):
        """SSE with no API key at all returns 401."""
        resp = await client.get("/v1/events/stream")
        assert resp.status_code == 401
        body = resp.json()
        assert body["type"].endswith("/missing-key")

    async def test_sse_valid_key_still_streams(self, client, api_key):
        """SSE with a valid key still returns 200 with text/event-stream."""
        resp = await client.get(
            "/v1/events/stream",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


# =========================================================================
# P0: WebSocket Cloudflare compatibility
# =========================================================================


class TestWebSocketCloudflareCompat:
    """WebSocket handler should work through Cloudflare proxies."""

    def test_ws_accept_includes_upgrade_headers(self, sync_app_client):
        """WebSocket accept should include proper upgrade response headers.

        After a successful WS handshake, the connection should be usable.
        We verify by checking we can do the auth handshake successfully.
        """
        client = sync_app_client
        api_key = client.portal.call(_create_api_key, client.app.state)

        with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "auth_ok"

    def test_ws_http_get_returns_upgrade_required(self, sync_app_client):
        """A plain HTTP GET to the WS endpoint should return a helpful error
        suggesting the client check proxy/Cloudflare configuration.
        """
        client = sync_app_client
        resp = client.get("/v1/ws")
        # Should get an error response, not a 500
        assert resp.status_code in (400, 426)
        body = resp.json()
        assert (
            "websocket" in body.get("detail", "").lower()
            or "upgrade" in body.get("detail", "").lower()
            or "websocket" in json.dumps(body).lower()
        )


# =========================================================================
# P2: WebSocket API key in query params — header auth + warning
# =========================================================================


class TestWebSocketHeaderAuth:
    """WebSocket should support header-based auth and warn on query param auth."""

    def test_ws_query_param_auth_logs_warning(self, sync_app_client, caplog):
        """Using api_key query param should log a deprecation warning."""
        client = sync_app_client
        api_key = client.portal.call(_create_api_key, client.app.state)

        with caplog.at_level(logging.WARNING, logger="a2a.websocket"):
            with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "auth_ok"

        # Verify a warning was logged (without containing the actual key)
        ws_warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(ws_warnings) >= 1
        warning_text = " ".join(r.message for r in ws_warnings)
        assert "query" in warning_text.lower() or "deprecated" in warning_text.lower()
        # The actual API key value must NOT appear in the log
        assert api_key not in warning_text

    def test_ws_header_auth_via_x_forwarded_api_key(self, sync_app_client):
        """X-Forwarded-Api-Key header should be accepted for WebSocket auth."""
        client = sync_app_client
        api_key = client.portal.call(_create_api_key, client.app.state)

        with client.websocket_connect(
            "/v1/ws",
            headers={"X-Forwarded-Api-Key": api_key},
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "auth_ok"
            assert msg["agent_id"] == "fix-agent"

    def test_ws_header_auth_via_authorization_bearer(self, sync_app_client):
        """Authorization: Bearer header should be accepted for WebSocket auth."""
        client = sync_app_client
        api_key = client.portal.call(_create_api_key, client.app.state)

        with client.websocket_connect(
            "/v1/ws",
            headers={"Authorization": f"Bearer {api_key}"},
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "auth_ok"
            assert msg["agent_id"] == "fix-agent"

    def test_ws_header_auth_does_not_log_warning(self, sync_app_client, caplog):
        """Header-based auth should NOT trigger the query param deprecation warning."""
        client = sync_app_client
        api_key = client.portal.call(_create_api_key, client.app.state)

        with caplog.at_level(logging.WARNING, logger="a2a.websocket"):
            with client.websocket_connect(
                "/v1/ws",
                headers={"Authorization": f"Bearer {api_key}"},
            ) as ws:
                msg = ws.receive_json()
                assert msg["type"] == "auth_ok"

        ws_warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and "query" in r.message.lower()]
        assert len(ws_warnings) == 0

    def test_ws_message_auth_still_works(self, sync_app_client):
        """Message-based auth flow (send {"type":"auth"}) should still work."""
        client = sync_app_client
        api_key = client.portal.call(_create_api_key, client.app.state)

        with client.websocket_connect("/v1/ws") as ws:
            ws.send_json({"type": "auth", "api_key": api_key})
            msg = ws.receive_json()
            assert msg["type"] == "auth_ok"
            assert msg["agent_id"] == "fix-agent"

    def test_ws_invalid_header_key_returns_error(self, sync_app_client):
        """Invalid key via header should return an error frame, not crash."""
        client = sync_app_client
        with client.websocket_connect(
            "/v1/ws",
            headers={"X-Forwarded-Api-Key": "a2a_bad_invalid_header_key"},
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "invalid" in msg["message"].lower() or "expired" in msg["message"].lower()
