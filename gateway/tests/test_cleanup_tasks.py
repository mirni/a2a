"""Tests for periodic cleanup tasks and async webhook delivery."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# RateEventsCleanup task tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_events_cleanup_calls_storage():
    """RateEventsCleanup should call paywall_storage.cleanup_old_rate_events() on each tick."""
    from gateway.src.cleanup_tasks import RateEventsCleanup

    mock_storage = MagicMock()
    mock_storage.cleanup_old_rate_events = AsyncMock(return_value=5)

    task = RateEventsCleanup(paywall_storage=mock_storage, interval=0.05)
    bg = asyncio.create_task(task.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    assert mock_storage.cleanup_old_rate_events.call_count >= 2
    mock_storage.cleanup_old_rate_events.assert_called_with()


@pytest.mark.asyncio
async def test_rate_events_cleanup_handles_exceptions():
    """RateEventsCleanup must not crash on storage errors."""
    from gateway.src.cleanup_tasks import RateEventsCleanup

    mock_storage = MagicMock()
    mock_storage.cleanup_old_rate_events = AsyncMock(side_effect=RuntimeError("db locked"))

    task = RateEventsCleanup(paywall_storage=mock_storage, interval=0.05)
    bg = asyncio.create_task(task.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    # Should have kept running despite errors
    assert mock_storage.cleanup_old_rate_events.call_count >= 2


@pytest.mark.asyncio
async def test_rate_events_cleanup_cancellation():
    """RateEventsCleanup should handle cancellation gracefully."""
    from gateway.src.cleanup_tasks import RateEventsCleanup

    mock_storage = MagicMock()
    mock_storage.cleanup_old_rate_events = AsyncMock(return_value=0)

    task = RateEventsCleanup(paywall_storage=mock_storage, interval=3600)
    bg = asyncio.create_task(task.run())
    await asyncio.sleep(0.05)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    # Should not raise — task exited cleanly


# ---------------------------------------------------------------------------
# EventBusCleanup task tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_bus_cleanup_calls_cleanup():
    """EventBusCleanup should call event_bus.cleanup(older_than_seconds=86400)."""
    from gateway.src.cleanup_tasks import EventBusCleanup

    mock_bus = MagicMock()
    mock_bus.cleanup = AsyncMock(return_value=10)

    task = EventBusCleanup(event_bus=mock_bus, interval=0.05, older_than_seconds=86400)
    bg = asyncio.create_task(task.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    assert mock_bus.cleanup.call_count >= 2
    mock_bus.cleanup.assert_called_with(older_than_seconds=86400)


@pytest.mark.asyncio
async def test_event_bus_cleanup_handles_exceptions():
    """EventBusCleanup must not crash on errors."""
    from gateway.src.cleanup_tasks import EventBusCleanup

    mock_bus = MagicMock()
    mock_bus.cleanup = AsyncMock(side_effect=RuntimeError("db error"))

    task = EventBusCleanup(event_bus=mock_bus, interval=0.05, older_than_seconds=86400)
    bg = asyncio.create_task(task.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    assert mock_bus.cleanup.call_count >= 2


@pytest.mark.asyncio
async def test_event_bus_cleanup_cancellation():
    """EventBusCleanup should handle cancellation gracefully."""
    from gateway.src.cleanup_tasks import EventBusCleanup

    mock_bus = MagicMock()
    mock_bus.cleanup = AsyncMock(return_value=0)

    task = EventBusCleanup(event_bus=mock_bus, interval=3600, older_than_seconds=86400)
    bg = asyncio.create_task(task.run())
    await asyncio.sleep(0.05)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Async webhook delivery tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_deliver_does_not_await_send():
    """deliver() should use create_task for _send, not await it inline."""
    from gateway.src.webhooks import WebhookManager

    manager = WebhookManager("sqlite:///dummy.db")
    # Set up a minimal mock database
    mock_db = AsyncMock()
    manager._db = mock_db

    # Mock cursor that returns matching webhooks
    mock_row = {
        "id": "whk-test123",
        "agent_id": "agent-1",
        "url": "https://slow.example.com/hook",
        "event_types": '["test.event"]',
        "secret": "secret123",
        "created_at": 1000.0,
        "active": 1,
        "filter_agent_ids": None,
    }

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[mock_row])
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.commit = AsyncMock()

    # Mock _insert_delivery and _send
    manager._insert_delivery = AsyncMock(return_value=1)

    send_started = asyncio.Event()
    send_done = asyncio.Event()

    async def slow_send(webhook, delivery_id, event):
        send_started.set()
        await asyncio.sleep(0.5)  # Simulate slow endpoint
        send_done.set()

    manager._send = slow_send

    event = {"type": "test.event", "data": "hello"}

    # deliver() should return quickly without waiting for slow_send to complete
    await asyncio.wait_for(manager.deliver(event), timeout=0.2)

    # Give a moment for the task to start
    await asyncio.sleep(0.05)

    # The send should have started but not completed
    assert send_started.is_set(), "_send was never called"
    assert not send_done.is_set(), "_send completed — deliver() waited for it"

    # Clean up: wait for background task
    await asyncio.sleep(0.6)


@pytest.mark.asyncio
async def test_webhook_deliver_semaphore_limits_concurrency():
    """Webhook delivery should limit concurrent sends via a semaphore."""
    from gateway.src.webhooks import WebhookManager

    manager = WebhookManager("sqlite:///dummy.db")
    mock_db = AsyncMock()
    manager._db = mock_db

    # Create 15 webhook rows to exceed the semaphore limit of 10
    rows = []
    for i in range(15):
        rows.append(
            {
                "id": f"whk-{i:04d}",
                "agent_id": "agent-1",
                "url": f"https://example.com/hook{i}",
                "event_types": '["test.event"]',
                "secret": "secret",
                "created_at": 1000.0,
                "active": 1,
                "filter_agent_ids": None,
            }
        )

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=rows)
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.commit = AsyncMock()

    manager._insert_delivery = AsyncMock(return_value=1)

    # Track concurrent sends
    concurrent_count = 0
    max_concurrent = 0
    lock = asyncio.Lock()

    async def tracked_send(webhook, delivery_id, event):
        nonlocal concurrent_count, max_concurrent
        async with lock:
            concurrent_count += 1
            if concurrent_count > max_concurrent:
                max_concurrent = concurrent_count
        await asyncio.sleep(0.1)
        async with lock:
            concurrent_count -= 1

    manager._send = tracked_send

    event = {"type": "test.event", "data": "hello"}
    await manager.deliver(event)

    # Wait for all background tasks to finish
    await asyncio.sleep(0.5)

    assert max_concurrent <= 10, f"Too many concurrent sends: {max_concurrent} > 10"
    assert max_concurrent > 1, f"Semaphore should allow multiple concurrent sends, got {max_concurrent}"


@pytest.mark.asyncio
async def test_webhook_deliver_task_error_does_not_crash():
    """A failed _send task should not propagate exceptions to the event loop."""
    from gateway.src.webhooks import WebhookManager

    manager = WebhookManager("sqlite:///dummy.db")
    mock_db = AsyncMock()
    manager._db = mock_db

    mock_row = {
        "id": "whk-error",
        "agent_id": "agent-1",
        "url": "https://example.com/hook",
        "event_types": '["test.event"]',
        "secret": "secret123",
        "created_at": 1000.0,
        "active": 1,
        "filter_agent_ids": None,
    }

    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[mock_row])
    mock_db.execute = AsyncMock(return_value=mock_cursor)
    mock_db.commit = AsyncMock()

    manager._insert_delivery = AsyncMock(return_value=1)

    async def exploding_send(webhook, delivery_id, event):
        raise ConnectionError("network down")

    manager._send = exploding_send

    event = {"type": "test.event", "data": "hello"}

    # Should not raise
    await manager.deliver(event)
    # Allow background task to run and fail
    await asyncio.sleep(0.1)
