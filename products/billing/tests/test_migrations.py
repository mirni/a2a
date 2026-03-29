"""Tests for billing schema migrations (old-schema → new-schema CI pattern)."""

from __future__ import annotations

import os
import tempfile

import aiosqlite
import pytest

from src.storage import StorageBackend


# The original DDL *without* idempotency_key — simulates a pre-migration DB.
_OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets (
    agent_id   TEXT PRIMARY KEY,
    balance    REAL NOT NULL DEFAULT 0.0,
    org_id     TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    function        TEXT NOT NULL,
    cost            REAL NOT NULL,
    tokens          INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT,
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_agent   ON usage_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    amount      REAL NOT NULL,
    tx_type     TEXT NOT NULL,
    description TEXT,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_agent ON transactions(agent_id);

CREATE TABLE IF NOT EXISTS rate_policies (
    agent_id        TEXT PRIMARY KEY,
    max_calls_per_min  INTEGER,
    max_spend_per_day  REAL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_undelivered ON billing_events(delivered, created_at);

CREATE TABLE IF NOT EXISTS budget_caps (
    agent_id        TEXT PRIMARY KEY,
    daily_cap       REAL,
    monthly_cap     REAL,
    alert_threshold REAL NOT NULL DEFAULT 0.8
);
"""


@pytest.fixture
async def old_schema_dsn():
    """Create a DB file with the *old* schema (no idempotency_key), return DSN."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = await aiosqlite.connect(path)
    await db.executescript(_OLD_SCHEMA)
    await db.commit()
    await db.close()
    yield f"sqlite:///{path}"
    os.unlink(path)


class TestBillingMigrations:
    async def test_old_schema_migrates_on_connect(self, old_schema_dsn):
        """An existing DB without idempotency_key gets the column after connect()."""
        backend = StorageBackend(dsn=old_schema_dsn)
        await backend.connect()
        # idempotency_key should now work
        row_id = await backend.record_usage(
            agent_id="a1", function="test", cost=1.0, idempotency_key="key-1"
        )
        assert row_id is not None
        await backend.close()

    async def test_fresh_db_idempotent_on_second_connect(self, tmp_db):
        """Fresh DB → connect() twice → no errors (migrations are idempotent)."""
        backend = StorageBackend(dsn=tmp_db)
        await backend.connect()
        await backend.close()
        # Second connect — migrations should skip (already applied)
        backend2 = StorageBackend(dsn=tmp_db)
        await backend2.connect()
        assert True  # no exception
        await backend2.close()

    async def test_idempotency_dedup_after_migration(self, old_schema_dsn):
        """After migration, duplicate idempotency_key is deduplicated."""
        backend = StorageBackend(dsn=old_schema_dsn)
        await backend.connect()
        await backend.create_wallet("a1", 100.0)
        id1 = await backend.record_usage(
            agent_id="a1", function="f", cost=1.0, idempotency_key="dup"
        )
        id2 = await backend.record_usage(
            agent_id="a1", function="f", cost=1.0, idempotency_key="dup"
        )
        assert id1 == id2  # second insert returned existing row
        await backend.close()
