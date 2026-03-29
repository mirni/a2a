"""Tests for billing schema migrations — atomic migration workflow (TDD).

Tests verify that:
- connect() WITHOUT apply_migrations fails on old-schema DBs
- connect() WITH apply_migrations applies them
- Fresh DBs work without migrations (allow_fresh)
- Idempotency dedup still works after migration
"""

from __future__ import annotations

import os
import tempfile

import aiosqlite
import pytest

from src.storage import StorageBackend

try:
    from shared_src.migrate import SchemaVersionMismatchError
except ImportError:
    from src.migrate import SchemaVersionMismatchError


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
    async def test_connect_fails_if_old_schema_not_migrated(self, old_schema_dsn):
        """Old-schema DB without external migration raises SchemaVersionMismatchError."""
        backend = StorageBackend(dsn=old_schema_dsn)
        with pytest.raises(SchemaVersionMismatchError):
            await backend.connect()

    async def test_connect_succeeds_after_external_migration(self, old_schema_dsn):
        """Run migrations externally, then connect() succeeds."""
        try:
            from shared_src.migrate import run_migrations
        except ImportError:
            from src.migrate import run_migrations

        # Simulate external migration script
        db_path = old_schema_dsn.replace("sqlite:///", "")
        async with aiosqlite.connect(db_path) as db:
            await run_migrations(db, StorageBackend._MIGRATIONS)

        backend = StorageBackend(dsn=old_schema_dsn)
        await backend.connect()  # should NOT raise
        # idempotency_key should now work
        row_id = await backend.record_usage(
            agent_id="a1", function="test", cost=1.0, idempotency_key="key-1"
        )
        assert row_id is not None
        await backend.close()

    async def test_fresh_db_connect_succeeds(self, tmp_db):
        """Fresh DB (v0) connects successfully (allow_fresh=True)."""
        backend = StorageBackend(dsn=tmp_db)
        await backend.connect()  # should NOT raise
        assert True
        await backend.close()

    async def test_idempotency_dedup_after_migration(self, old_schema_dsn):
        """After migration, duplicate idempotency_key is deduplicated."""
        backend = StorageBackend(dsn=old_schema_dsn)
        await backend.connect(apply_migrations=True)
        await backend.create_wallet("a1", 100.0)
        id1 = await backend.record_usage(
            agent_id="a1", function="f", cost=1.0, idempotency_key="dup"
        )
        id2 = await backend.record_usage(
            agent_id="a1", function="f", cost=1.0, idempotency_key="dup"
        )
        assert id1 == id2  # second insert returned existing row
        await backend.close()

    async def test_fresh_db_idempotent_on_second_connect(self, tmp_db):
        """Fresh DB → connect(apply_migrations=True) twice → no errors."""
        backend = StorageBackend(dsn=tmp_db)
        await backend.connect(apply_migrations=True)
        await backend.close()
        # Second connect — migrations should skip (already applied)
        backend2 = StorageBackend(dsn=tmp_db)
        await backend2.connect(apply_migrations=True)
        assert True  # no exception
        await backend2.close()
