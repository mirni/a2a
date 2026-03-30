"""Periodic cleanup tasks for rate events and event bus.

These background tasks follow the same pattern as HealthMonitor and
SubscriptionScheduler: an async ``run()`` loop with try/except and sleep.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("a2a.cleanup")


class RateEventsCleanup:
    """Periodically purges old rate_events from paywall storage.

    Args:
        paywall_storage: A PaywallStorage instance with ``cleanup_old_rate_events()``.
        interval: Seconds between cleanup runs (default: 3600).
    """

    def __init__(self, paywall_storage, interval: float = 3600) -> None:
        self.paywall_storage = paywall_storage
        self.interval = interval

    async def run(self) -> None:
        """Polling loop -- calls cleanup_old_rate_events() every *interval* seconds.

        Catches all exceptions so the task never silently dies.
        """
        while True:
            try:
                deleted = await self.paywall_storage.cleanup_old_rate_events()
                logger.info("RateEventsCleanup: removed %d old rate events", deleted)
            except Exception:
                logger.exception("RateEventsCleanup: unexpected error during cleanup")
            await asyncio.sleep(self.interval)


class EventBusCleanup:
    """Periodically purges old events from the event bus.

    Args:
        event_bus: An EventBus instance with ``cleanup(older_than_seconds=...)``.
        interval: Seconds between cleanup runs (default: 3600).
        older_than_seconds: Events older than this are deleted (default: 86400 = 24h).
    """

    def __init__(
        self,
        event_bus,
        interval: float = 3600,
        older_than_seconds: float = 86400,
    ) -> None:
        self.event_bus = event_bus
        self.interval = interval
        self.older_than_seconds = older_than_seconds

    async def run(self) -> None:
        """Polling loop -- calls event_bus.cleanup() every *interval* seconds.

        Catches all exceptions so the task never silently dies.
        """
        while True:
            try:
                deleted = await self.event_bus.cleanup(older_than_seconds=self.older_than_seconds)
                logger.info("EventBusCleanup: removed %d old events", deleted)
            except Exception:
                logger.exception("EventBusCleanup: unexpected error during cleanup")
            await asyncio.sleep(self.interval)
