"""Billing event stream for external billing systems."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from .storage import StorageBackend

# Type alias for event handlers
EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class BillingEventStream:
    """Event stream that emits billing events to registered handlers.

    Supports both pull-based (polling) and push-based (handler callbacks) patterns.
    Events are persisted in SQLite and marked as delivered after successful processing.
    """

    storage: StorageBackend
    _handlers: list[EventHandler] = field(default_factory=list, init=False, repr=False)

    def on_event(self, handler: EventHandler) -> EventHandler:
        """Register an event handler. Can be used as a decorator.

        Example::

            @stream.on_event
            async def handle(event):
                print(event)
        """
        self._handlers.append(handler)
        return handler

    def remove_handler(self, handler: EventHandler) -> None:
        """Remove a previously registered event handler."""
        self._handlers.remove(handler)

    async def emit(self, event_type: str, agent_id: str, payload: dict[str, Any]) -> int:
        """Persist an event and dispatch to all registered handlers.

        Returns the event ID.
        """
        event_id = await self.storage.emit_event(event_type, agent_id, payload)

        event = {
            "id": event_id,
            "event_type": event_type,
            "agent_id": agent_id,
            "payload": payload,
        }

        # Dispatch to handlers (fire-and-forget style, but await all)
        if self._handlers:
            results = await asyncio.gather(
                *(h(event) for h in self._handlers),
                return_exceptions=True,
            )
            # Mark as delivered only if all handlers succeeded
            all_ok = all(not isinstance(r, Exception) for r in results)
            if all_ok:
                await self.storage.mark_event_delivered(event_id)

        return event_id

    async def get_pending(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get undelivered events (pull-based pattern)."""
        return await self.storage.get_pending_events(limit)

    async def acknowledge(self, event_id: int) -> None:
        """Mark an event as delivered (for pull-based consumers)."""
        await self.storage.mark_event_delivered(event_id)

    async def get_events(self, agent_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get all events for an agent."""
        return await self.storage.get_events(agent_id, limit)

    async def replay(self, agent_id: str, limit: int = 100) -> None:
        """Replay events for an agent through all registered handlers."""
        events = await self.storage.get_events(agent_id, limit)
        for event in reversed(events):  # oldest first
            await asyncio.gather(
                *(h(event) for h in self._handlers),
                return_exceptions=True,
            )
