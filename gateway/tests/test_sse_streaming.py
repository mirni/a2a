"""Tests for long-lived SSE streaming with heartbeat and periodic polling.

Covers:
  - Correct streaming response headers
  - Events streamed as they arrive (publish -> appears in stream)
  - Heartbeat comments sent periodically
  - since_id resumes from correct position
  - Last-Event-ID header respected for reconnection
  - Connection closes after max_connection_seconds
  - Client disconnection handled gracefully
  - agent_id filtering works
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from gateway.src.routes.sse import (
    SSEConfig,
    sse_event_generator,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_sse_stream(raw: str) -> list[dict]:
    """Parse SSE text into a list of event dicts.

    Each SSE event block is separated by a blank line.
    Lines starting with 'data:' contain JSON payload.
    Lines starting with 'id:' contain the event ID.
    Lines starting with ':' are comments (heartbeats).
    """
    events = []
    current: dict = {}
    for line in raw.split("\n"):
        if line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif line.startswith("id: "):
            current["id"] = line[4:]
        elif line.startswith(":"):
            # Comment line — could be heartbeat
            events.append({"comment": line[1:].strip()})
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


# ---------------------------------------------------------------------------
# Test: SSEConfig defaults (sync — no async fixtures needed)
# ---------------------------------------------------------------------------


class TestSSEConfig:
    """Tests for SSEConfig dataclass defaults."""

    def test_default_poll_interval(self):
        cfg = SSEConfig()
        assert cfg.poll_interval_seconds == 1.0

    def test_default_heartbeat_interval(self):
        cfg = SSEConfig()
        assert cfg.heartbeat_interval_seconds == 15.0

    def test_default_max_connection(self):
        cfg = SSEConfig()
        assert cfg.max_connection_seconds == 3600

    def test_custom_values(self):
        cfg = SSEConfig(
            poll_interval_seconds=0.5,
            heartbeat_interval_seconds=10.0,
            max_connection_seconds=1800,
        )
        assert cfg.poll_interval_seconds == 0.5
        assert cfg.heartbeat_interval_seconds == 10.0
        assert cfg.max_connection_seconds == 1800


# ---------------------------------------------------------------------------
# Test: Streaming response headers
# ---------------------------------------------------------------------------


async def test_sse_response_headers(client, api_key):
    """SSE endpoint returns correct streaming headers."""
    resp = await client.get(
        "/v1/events/stream",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    assert resp.headers.get("cache-control") == "no-cache"
    assert resp.headers.get("connection") == "keep-alive"
    assert resp.headers.get("x-accel-buffering") == "no"


# ---------------------------------------------------------------------------
# Test: Events include id: field for Last-Event-ID reconnection
# ---------------------------------------------------------------------------


async def test_events_include_id_field(client, api_key, app):
    """Each event in the SSE stream must include an id: field."""
    ctx = app.state.ctx
    event_id = await ctx.event_bus.publish(
        event_type="test.id_field",
        source="test-agent",
        payload={"msg": "hello"},
    )

    resp = await client.get(
        "/v1/events/stream",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    text = resp.text
    assert f"id: {event_id}" in text


# ---------------------------------------------------------------------------
# Test: since_id resumes from correct position
# ---------------------------------------------------------------------------


async def test_since_id_skips_old_events(client, api_key, app):
    """Events with id <= since_id should not appear in the stream."""
    ctx = app.state.ctx
    id1 = await ctx.event_bus.publish(
        event_type="test.since",
        source="test-agent",
        payload={"seq": 1},
    )
    await ctx.event_bus.publish(
        event_type="test.since",
        source="test-agent",
        payload={"seq": 2},
    )

    resp = await client.get(
        f"/v1/events/stream?since_id={id1}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    text = resp.text
    events = _parse_sse_stream(text)
    data_events = [e for e in events if "data" in e]
    # Only event 2 should appear
    assert len(data_events) >= 1
    assert all(e["data"]["payload"]["seq"] != 1 for e in data_events)
    assert any(e["data"]["payload"]["seq"] == 2 for e in data_events)


# ---------------------------------------------------------------------------
# Test: Last-Event-ID header for reconnection
# ---------------------------------------------------------------------------


async def test_last_event_id_header(client, api_key, app):
    """Last-Event-ID header should work like since_id for reconnection."""
    ctx = app.state.ctx
    id1 = await ctx.event_bus.publish(
        event_type="test.reconnect",
        source="test-agent",
        payload={"seq": 1},
    )
    await ctx.event_bus.publish(
        event_type="test.reconnect",
        source="test-agent",
        payload={"seq": 2},
    )

    resp = await client.get(
        "/v1/events/stream",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Last-Event-ID": str(id1),
        },
    )
    text = resp.text
    events = _parse_sse_stream(text)
    data_events = [e for e in events if "data" in e]
    # Only event 2 should appear (id1 is skipped)
    assert len(data_events) >= 1
    assert all(e["data"]["payload"]["seq"] != 1 for e in data_events)


# ---------------------------------------------------------------------------
# Test: agent_id filtering
# ---------------------------------------------------------------------------


async def test_agent_id_filter(client, api_key, app):
    """agent_id query param filters events by source field."""
    ctx = app.state.ctx
    await ctx.event_bus.publish(
        event_type="test.agent",
        source="agent-alice",
        payload={"from": "alice"},
    )
    await ctx.event_bus.publish(
        event_type="test.agent",
        source="agent-bob",
        payload={"from": "bob"},
    )

    resp = await client.get(
        "/v1/events/stream?agent_id=agent-alice",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    text = resp.text
    events = _parse_sse_stream(text)
    data_events = [e for e in events if "data" in e]
    # Only alice's event should appear
    assert len(data_events) >= 1
    assert all(e["data"]["source"] == "agent-alice" for e in data_events)


# ---------------------------------------------------------------------------
# Test: sse_event_generator - heartbeat is sent
# ---------------------------------------------------------------------------


async def test_heartbeat_sent(app):
    """The generator sends heartbeat comments at the configured interval."""
    ctx = app.state.ctx

    # Use very short intervals for testing
    config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=0.1,
        max_connection_seconds=0.4,
    )

    is_disconnected = AsyncMock(return_value=False)

    chunks: list[str] = []
    async for chunk in sse_event_generator(
        event_bus=ctx.event_bus,
        config=config,
        is_disconnected=is_disconnected,
        event_type=None,
        agent_id=None,
        since_id=0,
    ):
        chunks.append(chunk)

    joined = "".join(chunks)
    # Should contain at least one heartbeat comment
    assert ": heartbeat" in joined


# ---------------------------------------------------------------------------
# Test: sse_event_generator - max_connection_seconds causes closure
# ---------------------------------------------------------------------------


async def test_max_connection_closes_stream(app):
    """Stream should auto-close after max_connection_seconds."""
    ctx = app.state.ctx

    config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,  # no heartbeat during short test
        max_connection_seconds=0.2,
    )

    is_disconnected = AsyncMock(return_value=False)

    start = time.monotonic()
    chunks: list[str] = []
    async for chunk in sse_event_generator(
        event_bus=ctx.event_bus,
        config=config,
        is_disconnected=is_disconnected,
        event_type=None,
        agent_id=None,
        since_id=0,
    ):
        chunks.append(chunk)
    elapsed = time.monotonic() - start

    # Should have ended around max_connection_seconds (with some tolerance)
    assert elapsed < 1.0  # generous upper bound


# ---------------------------------------------------------------------------
# Test: sse_event_generator - client disconnect stops stream
# ---------------------------------------------------------------------------


async def test_client_disconnect_stops_stream(app):
    """Generator should exit when is_disconnected returns True."""
    ctx = app.state.ctx

    call_count = 0

    async def mock_disconnected():
        nonlocal call_count
        call_count += 1
        # Disconnect after a few calls
        return call_count > 3

    config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=60.0,
    )

    chunks: list[str] = []
    async for chunk in sse_event_generator(
        event_bus=ctx.event_bus,
        config=config,
        is_disconnected=mock_disconnected,
        event_type=None,
        agent_id=None,
        since_id=0,
    ):
        chunks.append(chunk)

    # Should have exited quickly, not run for 60 seconds
    assert call_count <= 10


# ---------------------------------------------------------------------------
# Test: sse_event_generator - events streamed as they arrive
# ---------------------------------------------------------------------------


async def test_events_streamed_as_published(app):
    """Events published during streaming should appear in the output."""
    ctx = app.state.ctx

    config = SSEConfig(
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        max_connection_seconds=0.5,
    )

    is_disconnected = AsyncMock(return_value=False)

    # Publish an event after a short delay
    async def delayed_publish():
        await asyncio.sleep(0.1)
        await ctx.event_bus.publish(
            event_type="test.live",
            source="test-source",
            payload={"live": True},
        )

    task = asyncio.create_task(delayed_publish())

    chunks: list[str] = []
    async for chunk in sse_event_generator(
        event_bus=ctx.event_bus,
        config=config,
        is_disconnected=is_disconnected,
        event_type=None,
        agent_id=None,
        since_id=0,
    ):
        chunks.append(chunk)

    await task

    joined = "".join(chunks)
    assert '"live": true' in joined or '"live":true' in joined


# ---------------------------------------------------------------------------
# Test: backward compatibility — auth still required
# ---------------------------------------------------------------------------


async def test_sse_still_requires_auth(client):
    """SSE endpoint without API key should still return 401."""
    resp = await client.get("/v1/events/stream")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test: backward compatibility — event_type filter still works
# ---------------------------------------------------------------------------


async def test_event_type_filter_still_works(client, api_key, app):
    """event_type query param should still filter events."""
    ctx = app.state.ctx
    await ctx.event_bus.publish(
        event_type="wanted",
        source="test",
        payload={"yes": True},
    )
    await ctx.event_bus.publish(
        event_type="unwanted",
        source="test",
        payload={"no": True},
    )

    resp = await client.get(
        "/v1/events/stream?event_type=wanted",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    text = resp.text
    assert "wanted" in text
    assert "unwanted" not in text
