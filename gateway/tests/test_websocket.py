"""Tests for WebSocket endpoint /v1/ws (Item 13).

Uses Starlette's TestClient for synchronous WebSocket testing.
The TestClient manages its own ASGI lifespan in a background thread.
All async operations (key creation, event publishing) run via ``portal.call()``.
"""

from __future__ import annotations

import time

import pytest

from starlette.testclient import TestClient

from gateway.src.app import create_app


# ---------------------------------------------------------------------------
# Helpers — thin async wrappers for ``portal.call()`` (positional args only)
# ---------------------------------------------------------------------------


async def _create_api_key(app_state, agent_id: str = "ws-agent", tier: str = "free") -> str:
    """Create an API key (async helper, run via portal.call)."""
    ctx = app_state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=1000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier=tier)
    return key_info["key"]


async def _publish_event(ctx, event_type, source, payload):
    """Publish an event on the EventBus (async helper)."""
    return await ctx.event_bus.publish(
        event_type=event_type,
        source=source,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_app_client(tmp_path, monkeypatch):
    """Provide a sync TestClient that manages the full ASGI lifespan.

    All databases are created in a temp directory.  Use ``portal.call()``
    to run async helpers on the ASGI event loop.
    """
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


# ---------------------------------------------------------------------------
# Test: WebSocket connection with valid API key via query param succeeds
# ---------------------------------------------------------------------------


def test_ws_auth_via_query_param(sync_app_client):
    """WebSocket connection with api_key query param should authenticate."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        assert msg["agent_id"] == "ws-agent"


# ---------------------------------------------------------------------------
# Test: WebSocket connection with auth message succeeds
# ---------------------------------------------------------------------------


def test_ws_auth_via_message(sync_app_client):
    """WebSocket connection with auth message should authenticate."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)

    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"type": "auth", "api_key": api_key})
        msg = ws.receive_json()
        assert msg["type"] == "auth_ok"
        assert msg["agent_id"] == "ws-agent"


# ---------------------------------------------------------------------------
# Test: WebSocket connection with invalid API key is rejected
# ---------------------------------------------------------------------------


def test_ws_auth_invalid_key_rejected(sync_app_client):
    """WebSocket connection with invalid API key should be rejected."""
    client = sync_app_client
    with client.websocket_connect("/v1/ws?api_key=a2a_bad_invalid123") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "invalid" in msg["message"].lower() or "expired" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Test: Messages before auth are rejected
# ---------------------------------------------------------------------------


def test_ws_message_before_auth_rejected(sync_app_client):
    """Non-auth messages before authentication should be rejected."""
    client = sync_app_client
    with client.websocket_connect("/v1/ws") as ws:
        ws.send_json({"type": "subscribe", "event_types": ["billing.*"]})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "auth" in msg["message"].lower()


# ---------------------------------------------------------------------------
# Test: subscribe to event type, publish event, receive it via WebSocket
# ---------------------------------------------------------------------------


def test_ws_subscribe_and_receive_event(sync_app_client):
    """After subscribing, published events should be delivered via WebSocket."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)
    ctx = client.app.state.ctx

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        ws.send_json({"type": "subscribe", "event_types": ["billing.deposit"]})
        time.sleep(0.1)

        event_id = client.portal.call(
            _publish_event, ctx, "billing.deposit", "test", {"amount": "100.00"}
        )

        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["event_type"] == "billing.deposit"
        assert msg["data"]["amount"] == "100.00"
        assert msg["id"] == event_id


# ---------------------------------------------------------------------------
# Test: wildcard subscription
# ---------------------------------------------------------------------------


def test_ws_wildcard_subscribe(sync_app_client):
    """Wildcard subscription billing.* should match billing.deposit."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)
    ctx = client.app.state.ctx

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        ws.send_json({"type": "subscribe", "event_types": ["billing.*"]})
        time.sleep(0.1)

        client.portal.call(
            _publish_event, ctx, "billing.deposit", "test", {"amount": "50.00"}
        )

        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["event_type"] == "billing.deposit"


# ---------------------------------------------------------------------------
# Test: agent_id filtering
# ---------------------------------------------------------------------------


def test_ws_agent_id_filtering(sync_app_client):
    """Events with agent_id filter should only match the specified agent."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state, "ws-agent-2")
    ctx = client.app.state.ctx

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        ws.send_json({
            "type": "subscribe",
            "event_types": ["billing.deposit"],
            "agent_id": "ws-agent-2",
        })
        time.sleep(0.1)

        # Event for a different agent -- should NOT be delivered
        client.portal.call(
            _publish_event, ctx, "billing.deposit", "test",
            {"amount": "200.00", "agent_id": "other-agent"},
        )

        # Event for our agent -- should be delivered
        client.portal.call(
            _publish_event, ctx, "billing.deposit", "test",
            {"amount": "300.00", "agent_id": "ws-agent-2"},
        )

        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["data"]["agent_id"] == "ws-agent-2"
        assert msg["data"]["amount"] == "300.00"


# ---------------------------------------------------------------------------
# Test: heartbeat is sent periodically
# ---------------------------------------------------------------------------


def test_ws_heartbeat(sync_app_client):
    """Server should send heartbeat messages periodically."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)

    with client.websocket_connect(
        f"/v1/ws?api_key={api_key}&heartbeat_interval=1"
    ) as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        ws.send_json({"type": "subscribe", "event_types": ["test.*"]})

        # Wait for heartbeat -- with 1s interval we should get one
        time.sleep(1.5)
        msg = ws.receive_json()
        assert msg["type"] == "heartbeat"
        assert "timestamp" in msg


# ---------------------------------------------------------------------------
# Test: last_event_id reconnection
# ---------------------------------------------------------------------------


def test_ws_last_event_id_reconnection(sync_app_client):
    """Subscribe with last_event_id should replay missed events."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)
    ctx = client.app.state.ctx

    # Publish events before connecting
    id1 = client.portal.call(
        _publish_event, ctx, "billing.deposit", "test", {"seq": 1}
    )
    id2 = client.portal.call(
        _publish_event, ctx, "billing.deposit", "test", {"seq": 2}
    )

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        # Subscribe with last_event_id = id1 (should replay id2 onward)
        ws.send_json({
            "type": "subscribe",
            "event_types": ["billing.deposit"],
            "last_event_id": id1,
        })

        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["id"] == id2
        assert msg["data"]["seq"] == 2


# ---------------------------------------------------------------------------
# Test: unsubscribe stops event delivery
# ---------------------------------------------------------------------------


def test_ws_unsubscribe(sync_app_client):
    """Unsubscribe should stop event delivery."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)
    ctx = client.app.state.ctx

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        ws.send_json({"type": "subscribe", "event_types": ["billing.deposit"]})
        time.sleep(0.1)

        # Publish first event -- should arrive
        client.portal.call(
            _publish_event, ctx, "billing.deposit", "test", {"seq": 1}
        )
        msg = ws.receive_json()
        assert msg["type"] == "event"
        assert msg["data"]["seq"] == 1

        # Unsubscribe
        ws.send_json({"type": "unsubscribe"})
        time.sleep(0.1)

        # Publish another event -- should NOT arrive
        client.portal.call(
            _publish_event, ctx, "billing.deposit", "test", {"seq": 2}
        )

        # Send a ping to flush -- next message should be pong, not event
        time.sleep(0.2)
        ws.send_json({"type": "ping"})
        msg = ws.receive_json()
        # After unsubscribe, we should get pong, not event
        assert msg["type"] != "event" or msg["data"].get("seq") != 2


# ---------------------------------------------------------------------------
# Negative test: malformed JSON is handled gracefully
# ---------------------------------------------------------------------------


def test_ws_malformed_json(sync_app_client):
    """Malformed JSON should return an error message, not crash."""
    client = sync_app_client
    api_key = client.portal.call(_create_api_key, client.app.state)

    with client.websocket_connect(f"/v1/ws?api_key={api_key}") as ws:
        auth_msg = ws.receive_json()
        assert auth_msg["type"] == "auth_ok"

        ws.send_text("not valid json{{{")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "json" in msg["message"].lower() or "parse" in msg["message"].lower()
