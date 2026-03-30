"""GET /v1/events/stream — Server-Sent Events endpoint.

Long-lived SSE connection with periodic polling, heartbeat, and
auto-close after a configurable maximum duration.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from gateway.src.auth import extract_api_key
from gateway.src.errors import error_response


@dataclass
class SSEConfig:
    """Tuneable parameters for the SSE streaming connection."""

    poll_interval_seconds: float = 1.0
    heartbeat_interval_seconds: float = 15.0
    max_connection_seconds: int = 3600


async def sse_event_generator(
    *,
    event_bus: Any,
    config: SSEConfig,
    is_disconnected: Callable[[], Coroutine[Any, Any, bool]],
    event_type: str | None,
    agent_id: str | None,
    since_id: int,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted event chunks with heartbeat and polling.

    This is a pure async generator — all I/O dependencies are injected,
    making it straightforward to test in isolation.

    Args:
        event_bus: The event bus instance with a ``get_events`` method.
        config: Timing configuration for poll, heartbeat, and max duration.
        is_disconnected: Async callable returning True when client has gone.
        event_type: Optional filter by event type.
        agent_id: Optional filter by event source (agent ID).
        since_id: Only return events with id > since_id.
    """
    current_since_id = since_id
    start = time.monotonic()
    last_heartbeat = start

    while True:
        # --- Check max connection duration ---
        elapsed = time.monotonic() - start
        if elapsed >= config.max_connection_seconds:
            break

        # --- Check client disconnect ---
        if await is_disconnected():
            break

        # --- Poll for new events ---
        events = await event_bus.get_events(
            event_type=event_type,
            since_id=current_since_id,
            limit=100,
        )

        for event in events:
            # Filter by agent_id (source field) if requested
            if agent_id is not None:
                if isinstance(event, dict) and event.get("source") != agent_id:
                    # Still advance the cursor past this event
                    if isinstance(event, dict) and "id" in event:
                        current_since_id = max(current_since_id, event["id"])
                    continue

            data = json.dumps(event)
            # Include id: field for Last-Event-ID reconnection support
            if isinstance(event, dict) and "id" in event:
                event_id = event["id"]
                current_since_id = max(current_since_id, event_id)
                yield f"id: {event_id}\ndata: {data}\n\n"
            else:
                yield f"data: {data}\n\n"

        # --- Heartbeat ---
        now = time.monotonic()
        if now - last_heartbeat >= config.heartbeat_interval_seconds:
            yield ": heartbeat\n\n"
            last_heartbeat = now

        # --- Sleep until next poll ---
        await asyncio.sleep(config.poll_interval_seconds)


async def event_stream(request: Request) -> Response:
    """Stream events via Server-Sent Events (SSE).

    Requires API key via Authorization header.
    Accepts query params:
      - event_type (optional): filter by event type
      - since_id (optional): only events after this ID
      - agent_id (optional): filter events by source agent
    Accepts headers:
      - Last-Event-ID: resume from this event ID (overrides since_id)
    """
    # --- Auth ---
    raw_key = extract_api_key(request)
    if not raw_key:
        return await error_response(401, "Missing API key", "missing_key", request=request)

    ctx = request.app.state.ctx
    try:
        await ctx.key_manager.validate_key(raw_key)
    except Exception:
        return await error_response(401, "Invalid API key", "invalid_key", request=request)

    # --- Parse params ---
    event_type = request.query_params.get("event_type")
    agent_id = request.query_params.get("agent_id")
    since_id = int(request.query_params.get("since_id", "0"))

    # Last-Event-ID header takes precedence for reconnection
    last_event_id = request.headers.get("last-event-id")
    if last_event_id is not None:
        try:
            since_id = int(last_event_id)
        except ValueError:
            pass

    # --- Config (allow override via app.state for testing) ---
    config: SSEConfig = getattr(request.app.state, "sse_config", None) or SSEConfig()

    async def is_disconnected() -> bool:
        return await request.is_disconnected()

    return StreamingResponse(
        sse_event_generator(
            event_bus=ctx.event_bus,
            config=config,
            is_disconnected=is_disconnected,
            event_type=event_type,
            agent_id=agent_id,
            since_id=since_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


routes = [Route("/v1/events/stream", event_stream, methods=["GET"])]
