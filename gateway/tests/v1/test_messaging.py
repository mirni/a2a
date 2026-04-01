"""Tests for messaging REST endpoints — /v1/messaging/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# POST /v1/messaging/messages  (send_message)
# ---------------------------------------------------------------------------


async def test_send_message_via_rest(client, api_key):
    resp = await client.post(
        "/v1/messaging/messages",
        json={
            "sender": "test-agent",
            "recipient": "other-agent",
            "message_type": "text",
            "subject": "Hello",
            "body": "Hi there",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert body["sender"] == "test-agent"


async def test_send_message_no_auth(client):
    resp = await client.post(
        "/v1/messaging/messages",
        json={"sender": "a", "recipient": "b", "message_type": "text"},
    )
    assert resp.status_code == 401


async def test_send_message_extra_fields(client, api_key):
    resp = await client.post(
        "/v1/messaging/messages",
        json={"sender": "a", "recipient": "b", "message_type": "text", "extra": 1},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/messaging/messages  (get_messages)
# ---------------------------------------------------------------------------


async def test_get_messages_via_rest(client, api_key):
    resp = await client.get(
        "/v1/messaging/messages?agent_id=test-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "messages" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/messaging/negotiations  (negotiate_price)
# ---------------------------------------------------------------------------


async def test_negotiate_price_via_rest(client, api_key):
    resp = await client.post(
        "/v1/messaging/negotiations",
        json={
            "initiator": "test-agent",
            "responder": "other-agent",
            "amount": "50.00",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


async def test_negotiate_price_extra_fields(client, api_key):
    resp = await client.post(
        "/v1/messaging/negotiations",
        json={"initiator": "a", "responder": "b", "amount": "10", "extra": 1},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------


async def test_messaging_response_headers(client, api_key):
    resp = await client.get(
        "/v1/messaging/messages?agent_id=test-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers
