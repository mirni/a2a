"""Tests for shared_src/storage_migrations.py.

`apply_column_migrations` is the hygiene fix for audit finding C2:
older DBs shipped without columns that newer `CREATE INDEX` statements
reference, causing `executescript(_SCHEMA)` to raise
``OperationalError: no such column: <field>`` at startup.

The helper must:

1. Add missing columns idempotently (via ALTER TABLE ADD COLUMN).
2. Skip tables that don't exist yet (fresh-DB case — executescript
   will create them on the *next* step).
3. Skip columns that are already present (re-connect case).
4. Be safe to call with an empty migration list (new storage modules
   register the hook before they have any migrations to apply).
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

try:
    from shared_src.storage_migrations import apply_column_migrations
except ImportError:  # pragma: no cover — resolved via src.* in module tests
    from src.storage_migrations import apply_column_migrations


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _open(tmp_path: Path, name: str = "db.sqlite") -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(tmp_path / name))
    db.row_factory = aiosqlite.Row
    return db


async def _columns(db: aiosqlite.Connection, table: str) -> list[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in await cursor.fetchall()]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


async def test_empty_migration_list_is_noop(tmp_path: Path) -> None:
    """A freshly-added storage module may register an empty list."""
    db = await _open(tmp_path)
    await apply_column_migrations(db, [])
    # No error, no side effect.
    await db.close()


async def test_skips_missing_table(tmp_path: Path) -> None:
    """If the table doesn't exist yet (fresh DB), the helper must not fail.
    executescript(_SCHEMA) will create it in the next startup step."""
    db = await _open(tmp_path)
    await apply_column_migrations(db, [("not_yet_a_table", "new_col", "TEXT")])
    await db.close()


async def test_adds_missing_column_to_existing_table(tmp_path: Path) -> None:
    """Old DB + new column registered → ALTER TABLE runs."""
    db = await _open(tmp_path)
    # Simulate an old DB with the v1.0 schema (no new_col).
    await db.execute("CREATE TABLE things (id TEXT PRIMARY KEY)")
    await db.commit()

    await apply_column_migrations(db, [("things", "new_col", "TEXT NOT NULL DEFAULT ''")])
    cols = await _columns(db, "things")
    assert "new_col" in cols
    await db.close()


async def test_idempotent_when_column_already_present(tmp_path: Path) -> None:
    """Re-running the helper must not ALTER a table that already has the column."""
    db = await _open(tmp_path)
    await db.execute("CREATE TABLE things (id TEXT PRIMARY KEY, new_col TEXT DEFAULT '')")
    await db.commit()

    # No exception, no duplicate column.
    await apply_column_migrations(db, [("things", "new_col", "TEXT")])
    cols = await _columns(db, "things")
    assert cols.count("new_col") == 1
    await db.close()


async def test_multiple_migrations_applied_in_order(tmp_path: Path) -> None:
    db = await _open(tmp_path)
    await db.execute("CREATE TABLE things (id TEXT PRIMARY KEY)")
    await db.execute("CREATE TABLE others (id TEXT PRIMARY KEY, name TEXT)")
    await db.commit()

    migrations = [
        ("things", "col_a", "TEXT"),
        ("things", "col_b", "INTEGER NOT NULL DEFAULT 0"),
        ("others", "col_c", "REAL"),
    ]
    await apply_column_migrations(db, migrations)

    assert "col_a" in await _columns(db, "things")
    assert "col_b" in await _columns(db, "things")
    assert "col_c" in await _columns(db, "others")
    await db.close()


async def test_commits_after_altering(tmp_path: Path) -> None:
    """Schema changes must be committed so a fresh connection sees them."""
    db_path = tmp_path / "db.sqlite"
    db = await aiosqlite.connect(str(db_path))
    await db.execute("CREATE TABLE things (id TEXT PRIMARY KEY)")
    await db.commit()

    await apply_column_migrations(db, [("things", "col_x", "TEXT")])
    await db.close()

    # Re-open; the column must be visible.
    db2 = await aiosqlite.connect(str(db_path))
    cursor = await db2.execute("PRAGMA table_info(things)")
    cols = [row[1] for row in await cursor.fetchall()]
    await db2.close()
    assert "col_x" in cols


async def test_mixed_existing_and_missing_columns(tmp_path: Path) -> None:
    """A realistic upgrade: some columns already exist (prior upgrade), some
    don't (current upgrade). The helper must only add the missing ones."""
    db = await _open(tmp_path)
    await db.execute("CREATE TABLE things (id TEXT PRIMARY KEY, old_col TEXT)")
    await db.commit()

    migrations = [
        ("things", "old_col", "TEXT"),  # already present
        ("things", "new_col", "TEXT"),  # not yet
    ]
    await apply_column_migrations(db, migrations)
    cols = await _columns(db, "things")
    assert cols.count("old_col") == 1
    assert "new_col" in cols
    await db.close()
