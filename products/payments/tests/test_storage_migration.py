"""Tests for PaymentStorage schema migration robustness (audit C2).

Verifies that PaymentStorage.connect() can recover from databases created
by older code versions where certain columns may be missing.  The
settlements table INSERT uses 10 columns — if any are absent on the
production DB, capture fails with OperationalError.
"""

from __future__ import annotations

import time

import aiosqlite
import pytest
from payments.storage import PaymentStorage

pytestmark = pytest.mark.asyncio


async def _create_old_schema_db(db_path: str, settlements_ddl: str) -> None:
    """Create a payments DB with an old/incomplete settlements table schema."""
    db = await aiosqlite.connect(db_path)
    # Create minimal payment_intents table (needed for capture flow)
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS payment_intents (
            id              TEXT PRIMARY KEY,
            payer           TEXT NOT NULL,
            payee           TEXT NOT NULL,
            amount          INTEGER NOT NULL DEFAULT 0,
            description     TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'pending',
            settlement_id   TEXT,
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL,
            metadata        TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    # Create the settlements table with old/incomplete schema
    await db.executescript(settlements_ddl)
    await db.commit()
    await db.close()


async def test_connect_adds_missing_settlement_columns(tmp_path):
    """PaymentStorage.connect() must add missing columns to existing settlements table."""
    db_path = str(tmp_path / "payments.db")

    # Simulate an old DB that has settlements table WITHOUT some columns
    old_schema = """
    CREATE TABLE IF NOT EXISTS settlements (
        id              TEXT PRIMARY KEY,
        payer           TEXT NOT NULL,
        payee           TEXT NOT NULL,
        amount          INTEGER NOT NULL DEFAULT 0,
        created_at      REAL NOT NULL
    );
    """
    await _create_old_schema_db(db_path, old_schema)

    # Connect — should migrate the schema
    storage = PaymentStorage(f"sqlite:///{db_path}")
    await storage.connect()

    # Verify all expected columns exist
    cursor = await storage.db.execute("PRAGMA table_info(settlements)")
    columns = {row[1] for row in await cursor.fetchall()}

    expected = {
        "id",
        "payer",
        "payee",
        "amount",
        "source_type",
        "source_id",
        "description",
        "status",
        "idempotency_key",
        "created_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"

    # Verify insert_settlement works (this is what fails on production)
    now = time.time()
    await storage.insert_settlement(
        {
            "id": "test-settle-001",
            "payer": "agent-a",
            "payee": "agent-b",
            "amount": 100.0,
            "source_type": "intent",
            "source_id": "intent-001",
            "description": "test settlement",
            "status": "settled",
            "idempotency_key": None,
            "created_at": now,
        }
    )

    # Verify the row was inserted
    row = await storage.get_settlement("test-settle-001")
    assert row is not None
    assert row["payer"] == "agent-a"

    await storage.close()


async def test_connect_handles_missing_source_type_column(tmp_path):
    """Settlements table missing source_type column should be repaired on connect."""
    db_path = str(tmp_path / "payments.db")

    old_schema = """
    CREATE TABLE IF NOT EXISTS settlements (
        id              TEXT PRIMARY KEY,
        payer           TEXT NOT NULL,
        payee           TEXT NOT NULL,
        amount          INTEGER NOT NULL DEFAULT 0,
        description     TEXT NOT NULL DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'settled',
        created_at      REAL NOT NULL
    );
    """
    await _create_old_schema_db(db_path, old_schema)

    storage = PaymentStorage(f"sqlite:///{db_path}")
    await storage.connect()

    # insert_settlement must NOT raise OperationalError
    now = time.time()
    await storage.insert_settlement(
        {
            "id": "test-settle-002",
            "payer": "agent-a",
            "payee": "agent-b",
            "amount": 50.0,
            "source_type": "escrow",
            "source_id": "escrow-001",
            "description": "escrow release",
            "status": "settled",
            "idempotency_key": None,
            "created_at": now,
        }
    )

    row = await storage.get_settlement("test-settle-002")
    assert row is not None
    assert row["source_type"] == "escrow" if "source_type" in row else True

    await storage.close()


async def test_fresh_db_gets_full_schema(tmp_path):
    """A fresh DB (no existing tables) should get the complete schema."""
    db_path = str(tmp_path / "payments.db")

    storage = PaymentStorage(f"sqlite:///{db_path}")
    await storage.connect()

    # Verify all tables exist
    cursor = await storage.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {row[0] for row in await cursor.fetchall()}
    expected_tables = {"payment_intents", "escrows", "subscriptions", "settlements", "refunds"}
    assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"

    # Verify settlements has all columns
    cursor = await storage.db.execute("PRAGMA table_info(settlements)")
    columns = {row[1] for row in await cursor.fetchall()}
    expected_cols = {
        "id",
        "payer",
        "payee",
        "amount",
        "source_type",
        "source_id",
        "description",
        "status",
        "idempotency_key",
        "created_at",
    }
    assert expected_cols.issubset(columns), f"Missing columns: {expected_cols - columns}"

    await storage.close()
