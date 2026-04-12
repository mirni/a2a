"""MSG7.1/MSG7.3 regression — messaging endpoints must not crash with 500.

The v1.2.9 audit found that ``send_message`` and ``create_negotiation``
return 500.  These tests verify proper type validation and error handling.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# send_message — MSG7.1
# ---------------------------------------------------------------------------


async def test_send_message_valid_type(client, api_key):
    """send_message with a valid MessageType string succeeds."""
    resp = await client.post(
        "/v1/messaging/messages",
        json={
            "sender": "test-agent",
            "recipient": "other-agent",
            "message_type": "text",
            "subject": "Audit test",
            "body": "This should work",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"


async def test_send_message_invalid_type_returns_422(client, api_key):
    """send_message with an invalid message_type should return 422, not 500."""
    resp = await client.post(
        "/v1/messaging/messages",
        json={
            "sender": "test-agent",
            "recipient": "other-agent",
            "message_type": "INVALID_TYPE_THAT_DOES_NOT_EXIST",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 422, f"Expected 422 for invalid message_type, got {resp.status_code}: {resp.text}"


async def test_send_message_all_valid_types(client, api_key):
    """All MessageType enum values should be accepted."""
    valid_types = ["text", "price_negotiation", "task_specification", "counter_offer", "accept", "reject"]
    for msg_type in valid_types:
        resp = await client.post(
            "/v1/messaging/messages",
            json={
                "sender": "test-agent",
                "recipient": "other-agent",
                "message_type": msg_type,
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 201, f"message_type={msg_type!r} failed with {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# negotiate_price — MSG7.3
# ---------------------------------------------------------------------------


async def test_negotiate_price_succeeds(client, api_key):
    """negotiate_price with valid params returns 200."""
    resp = await client.post(
        "/v1/messaging/negotiations",
        json={
            "initiator": "test-agent",
            "responder": "other-agent",
            "amount": "25.00",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"


async def test_negotiate_price_not_500(client, api_key):
    """negotiate_price must never return 500 for valid input."""
    resp = await client.post(
        "/v1/messaging/negotiations",
        json={
            "initiator": "test-agent",
            "responder": "other-agent",
            "amount": "100.00",
            "service_id": "svc-123",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code != 500, f"Got 500: {resp.text}"
