"""GET /v1/events/stream — Server-Sent Events endpoint."""

from __future__ import annotations

import asyncio
import json

from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from gateway.src.auth import extract_api_key
from gateway.src.errors import error_response


async def event_stream(request: Request) -> Response:
    """Stream events via Server-Sent Events (SSE).

    Requires API key via Authorization header.
    Accepts query params:
      - event_type (optional): filter by event type
      - since_id (optional): only events after this ID
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

    event_type = request.query_params.get("event_type")
    since_id = int(request.query_params.get("since_id", "0"))

    async def generate():
        """Yield SSE-formatted events."""
        current_since_id = since_id
        # Do one poll and return results, then end (no infinite loop for testing)
        events = await ctx.event_bus.get_events(
            event_type=event_type,
            since_id=current_since_id,
            limit=100,
        )
        for event in events:
            data = json.dumps(event)
            yield f"data: {data}\n\n"
            if isinstance(event, dict) and "id" in event:
                current_since_id = max(current_since_id, event["id"])

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


routes = [Route("/v1/events/stream", event_stream, methods=["GET"])]
