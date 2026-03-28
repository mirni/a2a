"""Tests verifying assert statements are replaced with proper RuntimeError."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_webhook_register_raises_without_connect():
    """WebhookManager.register raises RuntimeError if connect() not called."""
    from gateway.src.webhooks import WebhookManager

    wm = WebhookManager("sqlite:///dummy.db")
    with pytest.raises(RuntimeError, match="not connected"):
        await wm.register("agent-1", "http://example.com", ["test.event"], "secret")


@pytest.mark.asyncio
async def test_webhook_deliver_raises_without_connect():
    """WebhookManager.deliver raises RuntimeError if connect() not called."""
    from gateway.src.webhooks import WebhookManager

    wm = WebhookManager("sqlite:///dummy.db")
    with pytest.raises(RuntimeError, match="not connected"):
        await wm.deliver({"type": "test.event"})


@pytest.mark.asyncio
async def test_event_bus_publish_raises_without_connect():
    """EventBus.publish raises RuntimeError if connect() not called."""
    from shared_src.event_bus import EventBus

    bus = EventBus(dsn="sqlite:///dummy.db")
    with pytest.raises(RuntimeError, match="not connected"):
        await bus.publish("test.event", "test", {})


@pytest.mark.asyncio
async def test_messaging_store_message_raises_without_connect():
    """MessageStorage.store_message raises RuntimeError if connect() not called."""
    from messaging_src.models import Message, MessageType
    from messaging_src.storage import MessageStorage

    storage = MessageStorage("sqlite:///dummy.db")
    msg = Message(
        sender="alice",
        recipient="bob",
        message_type=MessageType.TEXT,
        body="hello",
    )
    with pytest.raises(RuntimeError, match="not connected"):
        await storage.store_message(msg)
