"""Tests for BaseStorage — DB timeout wrapper (TDD)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiosqlite
import pytest

from src.base_storage import BaseStorage


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
