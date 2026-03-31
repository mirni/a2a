"""Tests for data retention policies: TTL-based cleanup of old records.

Verifies that:
- Old usage_records (>90 days) are cleaned up
- Old webhook_deliveries (>30 days) are cleaned up
- Old admin_audit_log records (>365 days) are cleaned up
- Cleanup tasks run without errors
- Recent records are NOT deleted
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

# ---------------------------------------------------------------------------
# Constants matching the retention policy
# ---------------------------------------------------------------------------
USAGE_RECORDS_TTL_DAYS = 90
WEBHOOK_DELIVERIES_TTL_DAYS = 30
ADMIN_AUDIT_LOG_TTL_DAYS = 365

DAY_SECONDS = 86400


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_billing_db(path: str) -> aiosqlite.Connection:
    """Create a minimal billing database with usage_records and admin_audit_log tables."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS usage_records (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            function        TEXT NOT NULL,
            cost            INTEGER NOT NULL DEFAULT 0,
            tokens          INTEGER NOT NULL DEFAULT 0,
            metadata        TEXT,
            created_at      REAL NOT NULL,
            idempotency_key TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);

        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       REAL NOT NULL,
            agent_id        TEXT NOT NULL,
            tool_name       TEXT NOT NULL,
            params_json     TEXT NOT NULL,
            client_ip       TEXT,
            status          TEXT NOT NULL CHECK(status IN ('success', 'denied', 'error')),
            result_summary  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_admin_audit_ts ON admin_audit_log(timestamp);
        """
    )
    await db.commit()
    return db


async def _create_webhook_db(path: str) -> aiosqlite.Connection:
    """Create a minimal webhook database with webhook_deliveries table."""
    db = await aiosqlite.connect(path)
    db.row_factory = aiosqlite.Row
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS webhooks (
            id               TEXT PRIMARY KEY,
            agent_id         TEXT NOT NULL,
            url              TEXT NOT NULL,
            event_types      TEXT NOT NULL,
            secret           TEXT NOT NULL,
            created_at       REAL NOT NULL,
            active           INTEGER NOT NULL DEFAULT 1,
            filter_agent_ids TEXT
        );

        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id      TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            payload         TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            last_attempt_at REAL,
            next_retry_at   REAL,
            response_code   INTEGER,
            response_body   TEXT,
            created_at      REAL NOT NULL,
            FOREIGN KEY (webhook_id) REFERENCES webhooks(id)
        );
        CREATE INDEX IF NOT EXISTS idx_deliveries_created ON webhook_deliveries(created_at);
        """
    )
    await db.commit()
    return db


async def _insert_usage_record(db: aiosqlite.Connection, agent_id: str, created_at: float) -> int:
    """Insert a usage record and return its id."""
    cursor = await db.execute(
        "INSERT INTO usage_records (agent_id, function, cost, tokens, created_at) VALUES (?, ?, ?, ?, ?)",
        (agent_id, "test_func", 100, 10, created_at),
    )
    await db.commit()
    return cursor.lastrowid


async def _insert_webhook_delivery(
    db: aiosqlite.Connection, webhook_id: str, created_at: float, status: str = "delivered"
) -> int:
    """Insert a webhook delivery record and return its id."""
    cursor = await db.execute(
        "INSERT INTO webhook_deliveries (webhook_id, event_type, payload, status, attempts, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (webhook_id, "test.event", '{"type": "test.event"}', status, 1, created_at),
    )
    await db.commit()
    return cursor.lastrowid


async def _insert_admin_audit(db: aiosqlite.Connection, agent_id: str, timestamp: float) -> int:
    """Insert an admin audit log record and return its id."""
    cursor = await db.execute(
        "INSERT INTO admin_audit_log (timestamp, agent_id, tool_name, params_json, status) "
        "VALUES (?, ?, ?, ?, ?)",
        (timestamp, agent_id, "test_tool", '{"key": "value"}', "success"),
    )
    await db.commit()
    return cursor.lastrowid


async def _count_rows(db: aiosqlite.Connection, table: str) -> int:
    """Count total rows in a table."""
    cursor = await db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
    row = await cursor.fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Tests: Usage records cleanup (>90 days)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_records_old_records_deleted(tmp_path):
    """Usage records older than 90 days should be deleted by cleanup."""
    from gateway.src.cleanup_tasks import UsageRecordsCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    # Insert old records (91 days ago)
    old_time = now - (91 * DAY_SECONDS)
    await _insert_usage_record(db, "agent-1", old_time)
    await _insert_usage_record(db, "agent-2", old_time)

    # Insert recent record (1 day ago)
    recent_time = now - (1 * DAY_SECONDS)
    await _insert_usage_record(db, "agent-1", recent_time)

    assert await _count_rows(db, "usage_records") == 3

    cleanup = UsageRecordsCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 2
    assert await _count_rows(db, "usage_records") == 1

    await db.close()


@pytest.mark.asyncio
async def test_usage_records_recent_records_not_deleted(tmp_path):
    """Usage records within the 90-day window should NOT be deleted."""
    from gateway.src.cleanup_tasks import UsageRecordsCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    # Insert records at various recent ages
    await _insert_usage_record(db, "agent-1", now - (1 * DAY_SECONDS))
    await _insert_usage_record(db, "agent-2", now - (30 * DAY_SECONDS))
    await _insert_usage_record(db, "agent-3", now - (89 * DAY_SECONDS))

    assert await _count_rows(db, "usage_records") == 3

    cleanup = UsageRecordsCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 0
    assert await _count_rows(db, "usage_records") == 3

    await db.close()


@pytest.mark.asyncio
async def test_usage_records_boundary_at_90_days(tmp_path):
    """Records well within the 90-day window should NOT be deleted; records beyond should be."""
    from gateway.src.cleanup_tasks import UsageRecordsCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    # Record at 89 days (safely within window -- should be kept)
    await _insert_usage_record(db, "agent-1", now - (89 * DAY_SECONDS))
    # Record at 91 days (should be deleted)
    await _insert_usage_record(db, "agent-2", now - (91 * DAY_SECONDS))

    cleanup = UsageRecordsCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 1
    assert await _count_rows(db, "usage_records") == 1

    await db.close()


@pytest.mark.asyncio
async def test_usage_records_cleanup_run_loop(tmp_path):
    """UsageRecordsCleanup.run() should execute cleanup periodically without error."""
    from gateway.src.cleanup_tasks import UsageRecordsCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    # Insert an old record
    await _insert_usage_record(db, "agent-1", now - (100 * DAY_SECONDS))

    cleanup = UsageRecordsCleanup(billing_db=db, interval=0.05)
    bg = asyncio.create_task(cleanup.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    # Old record should have been cleaned up
    assert await _count_rows(db, "usage_records") == 0

    await db.close()


# ---------------------------------------------------------------------------
# Tests: Webhook deliveries cleanup (>30 days)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_deliveries_old_records_deleted(tmp_path):
    """Webhook deliveries older than 30 days should be deleted by cleanup."""
    from gateway.src.cleanup_tasks import WebhookDeliveriesCleanup

    db = await _create_webhook_db(str(tmp_path / "webhooks.db"))
    now = time.time()

    # Insert old deliveries (31 days ago)
    old_time = now - (31 * DAY_SECONDS)
    await _insert_webhook_delivery(db, "whk-001", old_time)
    await _insert_webhook_delivery(db, "whk-002", old_time)

    # Insert recent delivery (1 day ago)
    recent_time = now - (1 * DAY_SECONDS)
    await _insert_webhook_delivery(db, "whk-001", recent_time)

    assert await _count_rows(db, "webhook_deliveries") == 3

    cleanup = WebhookDeliveriesCleanup(webhook_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 2
    assert await _count_rows(db, "webhook_deliveries") == 1

    await db.close()


@pytest.mark.asyncio
async def test_webhook_deliveries_recent_records_not_deleted(tmp_path):
    """Webhook deliveries within the 30-day window should NOT be deleted."""
    from gateway.src.cleanup_tasks import WebhookDeliveriesCleanup

    db = await _create_webhook_db(str(tmp_path / "webhooks.db"))
    now = time.time()

    await _insert_webhook_delivery(db, "whk-001", now - (1 * DAY_SECONDS))
    await _insert_webhook_delivery(db, "whk-002", now - (15 * DAY_SECONDS))
    await _insert_webhook_delivery(db, "whk-003", now - (29 * DAY_SECONDS))

    assert await _count_rows(db, "webhook_deliveries") == 3

    cleanup = WebhookDeliveriesCleanup(webhook_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 0
    assert await _count_rows(db, "webhook_deliveries") == 3

    await db.close()


@pytest.mark.asyncio
async def test_webhook_deliveries_boundary_at_30_days(tmp_path):
    """Records well within the 30-day window should be kept; records beyond deleted."""
    from gateway.src.cleanup_tasks import WebhookDeliveriesCleanup

    db = await _create_webhook_db(str(tmp_path / "webhooks.db"))
    now = time.time()

    # Record at 29 days (safely within window -- should be kept)
    await _insert_webhook_delivery(db, "whk-001", now - (29 * DAY_SECONDS))
    # Record at 31 days (should be deleted)
    await _insert_webhook_delivery(db, "whk-002", now - (31 * DAY_SECONDS))

    cleanup = WebhookDeliveriesCleanup(webhook_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 1
    assert await _count_rows(db, "webhook_deliveries") == 1

    await db.close()


@pytest.mark.asyncio
async def test_webhook_deliveries_cleanup_run_loop(tmp_path):
    """WebhookDeliveriesCleanup.run() should execute cleanup periodically without error."""
    from gateway.src.cleanup_tasks import WebhookDeliveriesCleanup

    db = await _create_webhook_db(str(tmp_path / "webhooks.db"))
    now = time.time()

    await _insert_webhook_delivery(db, "whk-001", now - (35 * DAY_SECONDS))

    cleanup = WebhookDeliveriesCleanup(webhook_db=db, interval=0.05)
    bg = asyncio.create_task(cleanup.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    assert await _count_rows(db, "webhook_deliveries") == 0

    await db.close()


# ---------------------------------------------------------------------------
# Tests: Admin audit log cleanup (>365 days)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_audit_old_records_deleted(tmp_path):
    """Admin audit log records older than 365 days should be deleted."""
    from gateway.src.cleanup_tasks import AdminAuditLogCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    # Insert old records (366 days ago)
    old_time = now - (366 * DAY_SECONDS)
    await _insert_admin_audit(db, "admin-1", old_time)
    await _insert_admin_audit(db, "admin-2", old_time)

    # Insert recent record (1 day ago)
    recent_time = now - (1 * DAY_SECONDS)
    await _insert_admin_audit(db, "admin-1", recent_time)

    assert await _count_rows(db, "admin_audit_log") == 3

    cleanup = AdminAuditLogCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 2
    assert await _count_rows(db, "admin_audit_log") == 1

    await db.close()


@pytest.mark.asyncio
async def test_admin_audit_recent_records_not_deleted(tmp_path):
    """Admin audit log records within the 365-day window should NOT be deleted."""
    from gateway.src.cleanup_tasks import AdminAuditLogCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    await _insert_admin_audit(db, "admin-1", now - (1 * DAY_SECONDS))
    await _insert_admin_audit(db, "admin-2", now - (100 * DAY_SECONDS))
    await _insert_admin_audit(db, "admin-3", now - (364 * DAY_SECONDS))

    assert await _count_rows(db, "admin_audit_log") == 3

    cleanup = AdminAuditLogCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 0
    assert await _count_rows(db, "admin_audit_log") == 3

    await db.close()


@pytest.mark.asyncio
async def test_admin_audit_boundary_at_365_days(tmp_path):
    """Records well within the 365-day window should be kept; records beyond deleted."""
    from gateway.src.cleanup_tasks import AdminAuditLogCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    # Record at 364 days (safely within window -- should be kept)
    await _insert_admin_audit(db, "admin-1", now - (364 * DAY_SECONDS))
    # Record at 366 days (should be deleted)
    await _insert_admin_audit(db, "admin-2", now - (366 * DAY_SECONDS))

    cleanup = AdminAuditLogCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 1
    assert await _count_rows(db, "admin_audit_log") == 1

    await db.close()


@pytest.mark.asyncio
async def test_admin_audit_cleanup_run_loop(tmp_path):
    """AdminAuditLogCleanup.run() should execute cleanup periodically without error."""
    from gateway.src.cleanup_tasks import AdminAuditLogCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    now = time.time()

    await _insert_admin_audit(db, "admin-1", now - (400 * DAY_SECONDS))

    cleanup = AdminAuditLogCleanup(billing_db=db, interval=0.05)
    bg = asyncio.create_task(cleanup.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass

    assert await _count_rows(db, "admin_audit_log") == 0

    await db.close()


# ---------------------------------------------------------------------------
# Tests: Error handling -- cleanup tasks must not crash on exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_records_cleanup_handles_exceptions(tmp_path):
    """UsageRecordsCleanup must not crash on database errors."""
    from gateway.src.cleanup_tasks import UsageRecordsCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    await db.close()  # Close to force errors

    cleanup = UsageRecordsCleanup(billing_db=db, interval=0.05)
    bg = asyncio.create_task(cleanup.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass
    # Task should not have crashed -- if it did, the cancel would raise a different error


@pytest.mark.asyncio
async def test_webhook_deliveries_cleanup_handles_exceptions(tmp_path):
    """WebhookDeliveriesCleanup must not crash on database errors."""
    from gateway.src.cleanup_tasks import WebhookDeliveriesCleanup

    db = await _create_webhook_db(str(tmp_path / "webhooks.db"))
    await db.close()

    cleanup = WebhookDeliveriesCleanup(webhook_db=db, interval=0.05)
    bg = asyncio.create_task(cleanup.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_admin_audit_cleanup_handles_exceptions(tmp_path):
    """AdminAuditLogCleanup must not crash on database errors."""
    from gateway.src.cleanup_tasks import AdminAuditLogCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))
    await db.close()

    cleanup = AdminAuditLogCleanup(billing_db=db, interval=0.05)
    bg = asyncio.create_task(cleanup.run())
    await asyncio.sleep(0.12)
    bg.cancel()
    try:
        await bg
    except asyncio.CancelledError:
        pass


# ---------------------------------------------------------------------------
# Tests: Empty tables -- cleanup on empty tables should return 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_usage_records_cleanup_empty_table(tmp_path):
    """Cleanup on an empty usage_records table should return 0 deleted."""
    from gateway.src.cleanup_tasks import UsageRecordsCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))

    cleanup = UsageRecordsCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 0
    await db.close()


@pytest.mark.asyncio
async def test_webhook_deliveries_cleanup_empty_table(tmp_path):
    """Cleanup on an empty webhook_deliveries table should return 0 deleted."""
    from gateway.src.cleanup_tasks import WebhookDeliveriesCleanup

    db = await _create_webhook_db(str(tmp_path / "webhooks.db"))

    cleanup = WebhookDeliveriesCleanup(webhook_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 0
    await db.close()


@pytest.mark.asyncio
async def test_admin_audit_cleanup_empty_table(tmp_path):
    """Cleanup on an empty admin_audit_log table should return 0 deleted."""
    from gateway.src.cleanup_tasks import AdminAuditLogCleanup

    db = await _create_billing_db(str(tmp_path / "billing.db"))

    cleanup = AdminAuditLogCleanup(billing_db=db, interval=3600)
    deleted = await cleanup.cleanup_once()

    assert deleted == 0
    await db.close()
