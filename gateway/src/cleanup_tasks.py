"""Periodic cleanup tasks for rate events, event bus, nonces, data lifecycle,
and TTL-based data retention (usage records, webhook deliveries, admin audit log).

These background tasks follow the same pattern as HealthMonitor and
SubscriptionScheduler: an async ``run()`` loop with try/except and sleep.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger("a2a.cleanup")

# Retention TTLs (in days)
_USAGE_RECORDS_TTL_DAYS = 90
_WEBHOOK_DELIVERIES_TTL_DAYS = 30
_ADMIN_AUDIT_LOG_TTL_DAYS = 365
_DAY_SECONDS = 86400


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


class NonceCleanup:
    """Periodically purges expired submission nonces from identity storage.

    Args:
        identity_storage: An IdentityStorage instance with ``cleanup_expired_nonces()``.
        interval: Seconds between cleanup runs (default: 3600).
        ttl_seconds: Nonces older than this are deleted (default: 300 = 5 min).
    """

    def __init__(
        self,
        identity_storage,
        interval: float = 3600,
        ttl_seconds: float = 300,
    ) -> None:
        self.identity_storage = identity_storage
        self.interval = interval
        self.ttl_seconds = ttl_seconds

    async def run(self) -> None:
        """Polling loop -- calls cleanup_expired_nonces() every *interval* seconds."""
        while True:
            try:
                deleted = await self.identity_storage.cleanup_expired_nonces(ttl_seconds=self.ttl_seconds)
                logger.info("NonceCleanup: removed %d expired nonces", deleted)
            except Exception:
                logger.exception("NonceCleanup: unexpected error during cleanup")
            await asyncio.sleep(self.interval)


class DataLifecycleTask:
    """Periodically runs data lifecycle operations: hot->warm, warm->cold, nonce rotation.

    Args:
        identity_storage: An IdentityStorage instance.
        interval: Seconds between lifecycle runs (default: 86400 = daily).
    """

    def __init__(self, identity_storage, interval: float = 86400) -> None:
        self.identity_storage = identity_storage
        self.interval = interval

    async def run(self) -> None:
        """Polling loop -- runs lifecycle compression every *interval* seconds."""
        from identity_src.data_lifecycle import DataLifecycleManager

        manager = DataLifecycleManager(self.identity_storage)
        while True:
            try:
                hot_deleted = await manager.compress_hot_to_warm()
                logger.info("DataLifecycle: hot->warm compressed %d rows", hot_deleted)

                cold_deleted = await manager.compress_warm_to_cold()
                logger.info("DataLifecycle: warm->cold compressed %d rows", cold_deleted)

                nonces_deleted = await manager.rotate_audit_logs()
                logger.info("DataLifecycle: rotated %d old nonces", nonces_deleted)

                usage = await manager.check_disk_usage()
                if usage["warning"]:
                    logger.warning(
                        "DataLifecycle: disk usage at %.1f%% (%d bytes)",
                        usage["pct_used"],
                        usage["db_size_bytes"],
                    )
            except Exception:
                logger.exception("DataLifecycle: unexpected error during lifecycle run")
            await asyncio.sleep(self.interval)


class AggregateRefreshTask:
    """Periodically refreshes metric aggregates for agents with recent submissions.

    Args:
        identity_storage: An IdentityStorage instance.
        interval: Seconds between refresh runs (default: 3600).
    """

    def __init__(self, identity_storage, interval: float = 3600) -> None:
        self.identity_storage = identity_storage
        self.interval = interval

    async def run(self) -> None:
        """Polling loop -- refreshes aggregates every *interval* seconds."""
        from identity_src.observability import compute_moving_averages

        while True:
            try:
                db = self.identity_storage.db
                # Find agents with recent timeseries data (within last interval)
                since = __import__("time").time() - self.interval
                cursor = await db.execute(
                    "SELECT DISTINCT agent_id, metric_name FROM metric_timeseries WHERE timestamp >= ?",
                    (since,),
                )
                pairs = await cursor.fetchall()
                for pair in pairs:
                    await compute_moving_averages(self.identity_storage, pair["agent_id"], pair["metric_name"])
                if pairs:
                    logger.info("AggregateRefresh: refreshed %d agent-metric pairs", len(pairs))
            except Exception:
                logger.exception("AggregateRefresh: unexpected error during refresh")
            await asyncio.sleep(self.interval)


# ---------------------------------------------------------------------------
# TTL-based data retention cleanup tasks
# ---------------------------------------------------------------------------


class UsageRecordsCleanup:
    """Purges usage_records older than 90 days from the billing database.

    Args:
        billing_db: An aiosqlite Connection to the billing database.
        interval: Seconds between cleanup runs.
    """

    def __init__(self, billing_db, interval: float = 86400) -> None:
        self.billing_db = billing_db
        self.interval = interval

    async def cleanup_once(self) -> int:
        """Delete usage records older than the TTL. Returns number deleted."""
        cutoff = time.time() - (_USAGE_RECORDS_TTL_DAYS * _DAY_SECONDS)
        cursor = await self.billing_db.execute(
            "DELETE FROM usage_records WHERE created_at < ?", (cutoff,)
        )
        await self.billing_db.commit()
        return cursor.rowcount

    async def run(self) -> None:
        """Polling loop -- runs cleanup every *interval* seconds."""
        while True:
            try:
                deleted = await self.cleanup_once()
                logger.info("UsageRecordsCleanup: removed %d old records", deleted)
            except Exception:
                logger.exception("UsageRecordsCleanup: unexpected error")
            await asyncio.sleep(self.interval)


class WebhookDeliveriesCleanup:
    """Purges webhook_deliveries older than 30 days from the webhook database.

    Args:
        webhook_db: An aiosqlite Connection to the webhook database.
        interval: Seconds between cleanup runs.
    """

    def __init__(self, webhook_db, interval: float = 86400) -> None:
        self.webhook_db = webhook_db
        self.interval = interval

    async def cleanup_once(self) -> int:
        """Delete webhook deliveries older than the TTL. Returns number deleted."""
        cutoff = time.time() - (_WEBHOOK_DELIVERIES_TTL_DAYS * _DAY_SECONDS)
        cursor = await self.webhook_db.execute(
            "DELETE FROM webhook_deliveries WHERE created_at < ?", (cutoff,)
        )
        await self.webhook_db.commit()
        return cursor.rowcount

    async def run(self) -> None:
        """Polling loop -- runs cleanup every *interval* seconds."""
        while True:
            try:
                deleted = await self.cleanup_once()
                logger.info("WebhookDeliveriesCleanup: removed %d old deliveries", deleted)
            except Exception:
                logger.exception("WebhookDeliveriesCleanup: unexpected error")
            await asyncio.sleep(self.interval)


class AdminAuditLogCleanup:
    """Purges admin_audit_log records older than 365 days from the billing database.

    Args:
        billing_db: An aiosqlite Connection to the billing database.
        interval: Seconds between cleanup runs.
    """

    def __init__(self, billing_db, interval: float = 86400) -> None:
        self.billing_db = billing_db
        self.interval = interval

    async def cleanup_once(self) -> int:
        """Delete admin audit records older than the TTL. Returns number deleted."""
        cutoff = time.time() - (_ADMIN_AUDIT_LOG_TTL_DAYS * _DAY_SECONDS)
        cursor = await self.billing_db.execute(
            "DELETE FROM admin_audit_log WHERE timestamp < ?", (cutoff,)
        )
        await self.billing_db.commit()
        return cursor.rowcount

    async def run(self) -> None:
        """Polling loop -- runs cleanup every *interval* seconds."""
        while True:
            try:
                deleted = await self.cleanup_once()
                logger.info("AdminAuditLogCleanup: removed %d old audit records", deleted)
            except Exception:
                logger.exception("AdminAuditLogCleanup: unexpected error")
            await asyncio.sleep(self.interval)
