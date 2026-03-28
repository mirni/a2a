"""Tests for P3-21: SSE Streaming for Events (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_sse_endpoint_exists(client, api_key):
    """GET /v1/events/stream should return text/event-stream content type."""
    resp = await client.get(
        "/v1/events/stream",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # Should return 200 with event-stream content type
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


async def test_sse_requires_auth(client):
    """SSE endpoint without API key should return 401."""
    resp = await client.get("/v1/events/stream")
    assert resp.status_code == 401


async def test_sse_streams_existing_events(client, api_key, app):
    """SSE should stream events that exist in the event bus."""
    ctx = app.state.ctx
    # Publish an event first
    await ctx.event_bus.publish(
        event_type="test.event",
        source="test",
        payload={"message": "hello"},
    )

    resp = await client.get(
        "/v1/events/stream",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    # The body should contain SSE-formatted data
    text = resp.text
    assert "data:" in text


async def test_sse_filter_by_event_type(client, api_key, app):
    """SSE with event_type filter should only return matching events."""
    ctx = app.state.ctx
    await ctx.event_bus.publish(
        event_type="type_a",
        source="test",
        payload={"val": 1},
    )
    await ctx.event_bus.publish(
        event_type="type_b",
        source="test",
        payload={"val": 2},
    )

    resp = await client.get(
        "/v1/events/stream?event_type=type_a",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    text = resp.text
    assert "type_a" in text
