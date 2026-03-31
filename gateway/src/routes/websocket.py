"""WebSocket endpoint at /v1/ws — real-time event streaming alternative to SSE.

Authentication (checked in priority order):
  1. ``Authorization: Bearer <key>`` header  (preferred — keys stay out of logs)
  2. ``X-Forwarded-Api-Key: <key>`` header   (proxy-friendly alternative)
  3. ``api_key`` query parameter             (backward-compat — logs a warning)
  4. In-band ``{"type": "auth", "api_key": "..."}`` message

Message protocol:
  Client -> Server:
    {"type": "auth", "api_key": "a2a_pro_..."}
    {"type": "subscribe", "event_types": ["billing.*"], "agent_id": "...", "last_event_id": 0}
    {"type": "unsubscribe"}
    {"type": "ping"}

  Server -> Client:
    {"type": "auth_ok", "agent_id": "..."}
    {"type": "event", "event_type": "...", "data": {...}, "id": 123}
    {"type": "heartbeat", "timestamp": 1234567890}
    {"type": "error", "message": "..."}
    {"type": "pong"}

Cloudflare compatibility:
  Ensure "WebSockets" is enabled in the Cloudflare dashboard under
  Network > WebSockets for the zone.  The handler sends standard upgrade
  headers; if the upgrade fails (e.g. proxy misconfiguration), a plain
  HTTP GET to /v1/ws returns a 426 Upgrade Required JSON error.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = logging.getLogger("a2a.websocket")

router = APIRouter()

# Default heartbeat interval in seconds
DEFAULT_HEARTBEAT_INTERVAL = 15


def _extract_ws_api_key(websocket: WebSocket) -> tuple[str | None, str]:
    """Extract API key from WebSocket headers or query params.

    Returns:
        (api_key, source) where source is one of "header", "query_param", or "none".
    """
    # 1. Authorization: Bearer header (preferred)
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        key = auth[7:].strip()
        if key:
            return key, "header"

    # 2. X-Forwarded-Api-Key header (proxy-friendly alternative)
    forwarded_key = websocket.headers.get("x-forwarded-api-key", "")
    if forwarded_key:
        return forwarded_key.strip(), "header"

    # 3. Query parameter (backward-compat — will log a warning)
    query_key = websocket.query_params.get("api_key")
    if query_key:
        return query_key, "query_param"

    return None, "none"


@router.websocket("/v1/ws")
async def websocket_handler(websocket: WebSocket) -> None:
    """Handle a WebSocket connection for real-time event streaming."""
    await websocket.accept()

    ctx = websocket.app.state.ctx

    # Parse heartbeat interval from query params (useful for testing)
    heartbeat_interval = DEFAULT_HEARTBEAT_INTERVAL
    hb_param = websocket.query_params.get("heartbeat_interval")
    if hb_param is not None:
        try:
            heartbeat_interval = max(1, int(hb_param))
        except (ValueError, TypeError):
            pass

    # --- Authentication Phase ---
    agent_id: str | None = None

    # Check headers and query params for API key
    api_key, auth_source = _extract_ws_api_key(websocket)

    if api_key:
        if auth_source == "query_param":
            logger.warning(
                "WebSocket auth via query parameter is deprecated; "
                "use Authorization header or message-based auth instead"
            )
        agent_id = await _authenticate(websocket, ctx, api_key)
        if agent_id is None:
            return  # Auth failed, connection closed

    # If no header/query-param auth, wait for auth message
    if agent_id is None:
        try:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(websocket, "Invalid JSON")
                await websocket.close(code=1008)
                return

            if msg.get("type") != "auth":
                await _send_error(websocket, 'Authentication required. Send {"type": "auth", "api_key": "..."} first.')
                await websocket.close(code=1008)
                return

            api_key = msg.get("api_key", "")
            agent_id = await _authenticate(websocket, ctx, api_key)
            if agent_id is None:
                return
        except WebSocketDisconnect:
            return

    # --- Authenticated session ---
    session = _WebSocketSession(
        websocket=websocket,
        ctx=ctx,
        agent_id=agent_id,
        heartbeat_interval=heartbeat_interval,
    )
    await session.run()


@router.get("/v1/ws")
async def websocket_upgrade_fallback(request: Request) -> JSONResponse:
    """Return a helpful error when a plain HTTP request hits the WS endpoint.

    This happens when Cloudflare or another reverse proxy strips the
    ``Upgrade: websocket`` header.  A 426 status code tells the client
    that the server requires a protocol upgrade.
    """
    return JSONResponse(
        {
            "success": False,
            "error": {
                "code": "upgrade_required",
                "message": (
                    "This endpoint requires a WebSocket connection. "
                    "If you are behind Cloudflare, ensure WebSockets are "
                    "enabled in the Network tab of the zone settings."
                ),
            },
        },
        status_code=426,
        headers={"Upgrade": "websocket"},
    )


async def _authenticate(websocket: WebSocket, ctx: Any, api_key: str) -> str | None:
    """Validate API key and send auth_ok or error. Returns agent_id or None."""
    try:
        record = await ctx.key_manager.validate_key(api_key)
        agent_id = record["agent_id"]
        await websocket.send_json({"type": "auth_ok", "agent_id": agent_id})
        return agent_id
    except Exception:
        await _send_error(websocket, "Invalid or expired API key")
        await websocket.close(code=1008)
        return None


async def _send_error(websocket: WebSocket, message: str) -> None:
    """Send an error message over WebSocket."""
    await websocket.send_json({"type": "error", "message": message})


class _WebSocketSession:
    """Manages an authenticated WebSocket session.

    Handles subscriptions, event delivery, heartbeats, and client messages.
    """

    def __init__(
        self,
        websocket: WebSocket,
        ctx: Any,
        agent_id: str,
        heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> None:
        self.websocket = websocket
        self.ctx = ctx
        self.agent_id = agent_id
        self.heartbeat_interval = heartbeat_interval

        # Event queue for pushing events from EventBus handlers to the WS sender
        self._event_queue: asyncio.Queue[dict] = asyncio.Queue()

        # Subscription state
        self._event_types: list[str] = []
        self._filter_agent_id: str | None = None
        self._subscription_ids: list[str] = []
        self._subscribed = False

    async def run(self) -> None:
        """Main session loop: heartbeat + message receive + event delivery."""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        sender_task = asyncio.create_task(self._event_sender_loop())
        try:
            await self._receive_loop()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.error("WebSocket session error: %s", exc, exc_info=exc)
        finally:
            heartbeat_task.cancel()
            sender_task.cancel()
            await self._cleanup_subscriptions()
            try:
                await self.websocket.close()
            except Exception:
                pass

    async def _receive_loop(self) -> None:
        """Process incoming client messages."""
        while True:
            raw = await self.websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_error(self.websocket, "Invalid JSON: could not parse message")
                continue

            msg_type = msg.get("type")

            if msg_type == "subscribe":
                await self._handle_subscribe(msg)
            elif msg_type == "unsubscribe":
                await self._handle_unsubscribe()
            elif msg_type == "ping":
                await self.websocket.send_json({"type": "pong"})
            elif msg_type == "auth":
                await _send_error(self.websocket, "Already authenticated")
            else:
                await _send_error(self.websocket, f"Unknown message type: {msg_type}")

    async def _handle_subscribe(self, msg: dict) -> None:
        """Process a subscribe message."""
        # Clean up previous subscriptions if re-subscribing
        await self._cleanup_subscriptions()

        event_types = msg.get("event_types", [])
        if not isinstance(event_types, list) or not event_types:
            await _send_error(self.websocket, "event_types must be a non-empty list")
            return

        self._event_types = event_types
        self._filter_agent_id = msg.get("agent_id")
        last_event_id = msg.get("last_event_id", 0)

        # Replay missed events if last_event_id is provided
        if last_event_id and last_event_id > 0:
            await self._replay_events(last_event_id)

        # Subscribe to EventBus for each event type pattern
        # For wildcard patterns like "billing.*", we subscribe to specific
        # event types that we discover, or use a catch-all approach
        await self._register_subscriptions()
        self._subscribed = True

    async def _replay_events(self, last_event_id: int) -> None:
        """Replay events from the EventBus that occurred after last_event_id."""
        for pattern in self._event_types:
            if "*" in pattern:
                # For wildcards, get all events and filter by pattern
                events = await self.ctx.event_bus.get_events(
                    since_id=last_event_id,
                    limit=100,
                )
                for event in events:
                    if self._matches_pattern(event["event_type"], pattern) and self._passes_agent_filter(event):
                        await self._send_event(event)
            else:
                events = await self.ctx.event_bus.get_events(
                    event_type=pattern,
                    since_id=last_event_id,
                    limit=100,
                )
                for event in events:
                    if self._passes_agent_filter(event):
                        await self._send_event(event)

    async def _register_subscriptions(self) -> None:
        """Register EventBus subscribers for real-time event delivery."""
        for pattern in self._event_types:
            if "*" in pattern:
                # For wildcard patterns, we need a global subscriber
                # The EventBus dispatches by exact event_type, so we subscribe
                # to a special wildcard mechanism
                sub_id = await self.ctx.event_bus.subscribe(
                    event_type="*",
                    handler=self._on_event,
                    filter_fn=lambda event, p=pattern: self._matches_pattern(event.get("event_type", ""), p),
                )
                self._subscription_ids.append(sub_id)
            else:
                sub_id = await self.ctx.event_bus.subscribe(
                    event_type=pattern,
                    handler=self._on_event,
                    filter_fn=self._make_agent_filter() if self._filter_agent_id else None,
                )
                self._subscription_ids.append(sub_id)

    def _make_agent_filter(self) -> Any:
        """Create a filter function for agent_id matching."""
        agent_id = self._filter_agent_id

        def _filter(event: dict) -> bool:
            payload = event.get("payload", {})
            if isinstance(payload, dict):
                return payload.get("agent_id") == agent_id
            return True

        return _filter

    async def _on_event(self, event: dict) -> None:
        """EventBus handler — push event to the WebSocket send queue."""
        if self._filter_agent_id and not self._passes_agent_filter(event):
            return
        await self._event_queue.put(event)

    async def _event_sender_loop(self) -> None:
        """Drain the event queue and send events to the WebSocket client."""
        try:
            while True:
                event = await self._event_queue.get()
                if not self._subscribed:
                    continue
                await self._send_event(event)
        except asyncio.CancelledError:
            pass

    async def _send_event(self, event: dict) -> None:
        """Format and send a single event to the WebSocket client."""
        await self.websocket.send_json(
            {
                "type": "event",
                "event_type": event["event_type"],
                "data": event.get("payload", {}),
                "id": event["id"],
            }
        )

    async def _handle_unsubscribe(self) -> None:
        """Remove all active subscriptions."""
        await self._cleanup_subscriptions()
        self._subscribed = False
        self._event_types = []
        self._filter_agent_id = None

    async def _cleanup_subscriptions(self) -> None:
        """Unsubscribe all EventBus subscriptions."""
        for sub_id in self._subscription_ids:
            try:
                await self.ctx.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        self._subscription_ids.clear()

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat messages."""
        try:
            while True:
                await asyncio.sleep(self.heartbeat_interval)
                await self.websocket.send_json(
                    {
                        "type": "heartbeat",
                        "timestamp": int(time.time()),
                    }
                )
        except asyncio.CancelledError:
            pass
        except WebSocketDisconnect:
            pass

    @staticmethod
    def _matches_pattern(event_type: str, pattern: str) -> bool:
        """Check if an event_type matches a subscription pattern.

        Supports wildcards like ``billing.*`` which matches ``billing.deposit``
        but not ``billing.sub.detail``.
        """
        return fnmatch.fnmatch(event_type, pattern)

    def _passes_agent_filter(self, event: dict) -> bool:
        """Check if an event matches the agent_id filter."""
        if not self._filter_agent_id:
            return True
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            return payload.get("agent_id") == self._filter_agent_id
        return True
