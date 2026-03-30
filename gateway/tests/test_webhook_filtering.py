"""Tests for webhook event filtering by agent_id (Item 8).

Covers:
- Webhook with filter_agent_ids only receives matching events
- Webhook without filter receives all events (backward compatible)
- Event with payer field matches filter
- Event with sender field matches filter
- Event with no agent fields is delivered to filtered webhooks (no false negatives)
- Multiple agent_ids in filter work
- Negative test: event for non-matching agent_id is NOT delivered
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _pending_deliveries(wm, webhook_id: str) -> list[dict]:
    """Return all delivery rows for a webhook."""
    rows = await wm.get_delivery_history(webhook_id)
    return rows


# ---------------------------------------------------------------------------
# Backward compatibility: no filter_agent_ids
# ---------------------------------------------------------------------------


async def test_no_filter_delivers_all_events(app):
    """A webhook registered without filter_agent_ids receives ALL matching events."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
    )

    # Deliver an event with agent_id="alice"
    await wm.deliver({"type": "billing.deposit", "agent_id": "alice", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1, "Unfiltered webhook must receive all matching events"


async def test_no_filter_delivers_event_without_agent_fields(app):
    """Unfiltered webhook receives events that have no agent-related fields."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["system.health"],
        secret="s3cret",
    )

    await wm.deliver({"type": "system.health", "status": "ok"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


# ---------------------------------------------------------------------------
# Filtered webhook: agent_id field
# ---------------------------------------------------------------------------


async def test_filter_matches_agent_id_field(app):
    """Webhook with filter_agent_ids delivers when event.agent_id is in the list."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    await wm.deliver({"type": "billing.deposit", "agent_id": "alice", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


# ---------------------------------------------------------------------------
# Negative test: non-matching agent_id
# ---------------------------------------------------------------------------


async def test_filter_rejects_non_matching_agent_id(app):
    """Webhook with filter_agent_ids must NOT receive events for other agents."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    await wm.deliver({"type": "billing.deposit", "agent_id": "bob", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 0, "Filtered webhook must NOT receive non-matching events"


# ---------------------------------------------------------------------------
# Filtered webhook: payer field
# ---------------------------------------------------------------------------


async def test_filter_matches_payer_field(app):
    """Event with 'payer' field matching filter_agent_ids is delivered."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    await wm.deliver({"type": "billing.deposit", "payer": "alice", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


# ---------------------------------------------------------------------------
# Filtered webhook: sender field
# ---------------------------------------------------------------------------


async def test_filter_matches_sender_field(app):
    """Event with 'sender' field matching filter_agent_ids is delivered."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    await wm.deliver({"type": "billing.deposit", "sender": "alice", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


# ---------------------------------------------------------------------------
# Filtered webhook: payee and recipient fields
# ---------------------------------------------------------------------------


async def test_filter_matches_payee_field(app):
    """Event with 'payee' field matching filter_agent_ids is delivered."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    await wm.deliver({"type": "billing.deposit", "payee": "alice", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


async def test_filter_matches_recipient_field(app):
    """Event with 'recipient' field matching filter_agent_ids is delivered."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    await wm.deliver({"type": "billing.deposit", "recipient": "alice", "amount": "10"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


# ---------------------------------------------------------------------------
# Multiple agent_ids in filter
# ---------------------------------------------------------------------------


async def test_filter_multiple_agent_ids(app):
    """Webhook with multiple filter_agent_ids delivers for any match."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice", "bob", "charlie"],
    )

    # event for bob should match
    await wm.deliver({"type": "billing.deposit", "agent_id": "bob", "amount": "5"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1


# ---------------------------------------------------------------------------
# No agent fields in event + filtered webhook
# ---------------------------------------------------------------------------


async def test_filter_delivers_event_with_no_agent_fields(app):
    """Filtered webhook delivers events with no agent-related fields (no false negatives)."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["system.health"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    # Event has no agent_id/payer/payee/sender/recipient
    await wm.deliver({"type": "system.health", "status": "ok"})

    deliveries = await _pending_deliveries(wm, wh["id"])
    assert len(deliveries) == 1, "Events with no agent fields must still be delivered"


# ---------------------------------------------------------------------------
# filter_agent_ids stored and returned
# ---------------------------------------------------------------------------


async def test_register_returns_filter_agent_ids(app):
    """register() result includes the filter_agent_ids list."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice", "bob"],
    )

    assert wh["filter_agent_ids"] == ["alice", "bob"]


async def test_register_without_filter_returns_none(app):
    """register() result has filter_agent_ids=None when not specified."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
    )

    assert wh["filter_agent_ids"] is None


# ---------------------------------------------------------------------------
# get_webhook returns filter_agent_ids
# ---------------------------------------------------------------------------


async def test_get_webhook_includes_filter_agent_ids(app):
    """get_webhook() returns the stored filter_agent_ids."""
    wm = app.state.ctx.webhook_manager

    wh = await wm.register(
        agent_id="owner-1",
        url="https://example.com/hook",
        event_types=["billing.deposit"],
        secret="s3cret",
        filter_agent_ids=["alice"],
    )

    fetched = await wm.get_webhook(wh["id"])
    assert fetched is not None
    assert fetched["filter_agent_ids"] == ["alice"]


# ---------------------------------------------------------------------------
# End-to-end via API
# ---------------------------------------------------------------------------


async def test_register_webhook_api_with_filter(client, pro_api_key, app):
    """register_webhook tool accepts filter_agent_ids via the API."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "register_webhook",
            "params": {
                "agent_id": "pro-agent",
                "url": "https://example.com/hook",
                "event_types": ["billing.deposit"],
                "secret": "my-secret-key",
                "filter_agent_ids": ["alice", "bob"],
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["result"]["filter_agent_ids"] == ["alice", "bob"]
