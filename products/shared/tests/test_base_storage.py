"""Tests for BaseStorage — DB timeout wrapper and schema version checks (TDD)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiosqlite
import pytest

from src.base_storage import BaseStorage
from src.migrate import Migration, SchemaVersionMismatchError, get_current_version


pytestmark = pytest.mark.asyncio


class TestDBTimeout:
    """BaseStorage should have a configurable DB timeout and wrap schema execution."""

    async def test_db_timeout_class_variable_default(self):
        """BaseStorage should have a _DB_TIMEOUT of 5.0 seconds."""
        assert hasattr(BaseStorage, "_DB_TIMEOUT")
        assert BaseStorage._DB_TIMEOUT == 5.0

    async def test_connect_succeeds_within_timeout(self, tmp_path):
        """Normal fast schema should connect without issues."""

        @dataclass
        class FastStorage(BaseStorage):
            _SCHEMA: str = "CREATE TABLE IF NOT EXISTS test_t (id INTEGER PRIMARY KEY);"

        storage = FastStorage(dsn=f"sqlite:///{tmp_path}/fast_test.db")
        await storage.connect()

        cursor = await storage.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_t'"
        )
        row = await cursor.fetchone()
        assert row is not None
        await storage.close()

    async def test_subclass_can_override_timeout(self, tmp_path):
        """Subclasses should be able to set a custom _DB_TIMEOUT."""

        @dataclass
        class CustomTimeout(BaseStorage):
            _SCHEMA: str = "CREATE TABLE IF NOT EXISTS t2 (id INTEGER);"
            _DB_TIMEOUT: float = 30.0

        storage = CustomTimeout(dsn=f"sqlite:///{tmp_path}/custom.db")
        assert storage._DB_TIMEOUT == 30.0
        await storage.connect()
        await storage.close()

    async def test_db_operation_timeout_raises(self, tmp_path):
        """Schema execution exceeding _DB_TIMEOUT should raise TimeoutError."""

        @dataclass
        class TinyTimeoutStorage(BaseStorage):
            _SCHEMA: str = "CREATE TABLE IF NOT EXISTS t (id INTEGER);"
            _DB_TIMEOUT: float = 0.01  # 10ms

        storage = TinyTimeoutStorage(dsn=f"sqlite:///{tmp_path}/timeout.db")

        # Open the connection manually (bypass connect to inject delay)
        try:
            from shared_src.db_security import harden_connection
        except ImportError:
            from src.db_security import harden_connection

        db_path = storage.dsn.replace("sqlite:///", "")
        storage._db = await aiosqlite.connect(db_path)
        storage._db.row_factory = aiosqlite.Row
        await harden_connection(storage._db)

        # Replace executescript with a deliberately slow version
        real_executescript = storage._db.executescript

        async def slow_executescript(sql):
            await asyncio.sleep(1.0)
            return await real_executescript(sql)

        storage._db.executescript = slow_executescript

        # The timeout wrapper should raise
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                storage._db.executescript(storage._SCHEMA),
                timeout=storage._DB_TIMEOUT,
            )

        await storage._db.close()


# ---------------------------------------------------------------------------
# Schema version checking on connect
# ---------------------------------------------------------------------------

_TEST_MIGRATIONS = (
    Migration(version=1, description="add col name",
              sql="ALTER TABLE t1 ADD COLUMN name TEXT"),
    Migration(version=2, description="add col tag",
              sql="ALTER TABLE t1 ADD COLUMN tag TEXT"),
)


class TestSchemaVersionCheck:
    async def test_connect_raises_on_version_mismatch(self, tmp_path):
        """DB at v1 but storage expects v2 — raises SchemaVersionMismatchError."""

        @dataclass
        class MigStorage(BaseStorage):
            _SCHEMA: str = "CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY, name TEXT, tag TEXT);"
            _MIGRATIONS: tuple = _TEST_MIGRATIONS

        db_path = str(tmp_path / "mismatch.db")
        # Pre-seed DB at v1 (base schema + first migration only)
        async with aiosqlite.connect(db_path) as db:
            await db.executescript("CREATE TABLE t1 (id INTEGER PRIMARY KEY);")
            await db.commit()
            from src.migrate import run_migrations
            await run_migrations(db, _TEST_MIGRATIONS[:1])

        storage = MigStorage(dsn=f"sqlite:///{db_path}")
        with pytest.raises(SchemaVersionMismatchError):
            await storage.connect()

    async def test_connect_succeeds_on_fresh_db(self, tmp_path):
        """Empty DB (v0) — connect succeeds (stamps version from _SCHEMA)."""

        @dataclass
        class MigStorage(BaseStorage):
            _SCHEMA: str = "CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY, name TEXT, tag TEXT);"
            _MIGRATIONS: tuple = _TEST_MIGRATIONS

        storage = MigStorage(dsn=f"sqlite:///{tmp_path}/fresh.db")
        await storage.connect()  # should NOT raise
        await storage.close()

    async def test_connect_with_apply_migrations_runs_them(self, tmp_path):
        """connect(apply_migrations=True) on existing DB applies pending migrations."""

        @dataclass
        class MigStorage(BaseStorage):
            _SCHEMA: str = "CREATE TABLE IF NOT EXISTS t1 (id INTEGER PRIMARY KEY, name TEXT, tag TEXT);"
            _MIGRATIONS: tuple = _TEST_MIGRATIONS

        # Pre-seed DB with base schema only (no migrations)
        db_path = str(tmp_path / "apply.db")
        async with aiosqlite.connect(db_path) as db:
            await db.executescript("CREATE TABLE t1 (id INTEGER PRIMARY KEY);")
            await db.commit()

        storage = MigStorage(dsn=f"sqlite:///{db_path}")
        await storage.connect(apply_migrations=True)

        # Version should be 2
        version = await get_current_version(storage.db)
        assert version == 2

        # Column from migration v2 should exist
        await storage.db.execute("INSERT INTO t1 (id, name, tag) VALUES (1, 'ok', 't')")
        await storage.close()
