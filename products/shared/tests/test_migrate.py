"""Tests for schema migration runner (TDD — written before implementation)."""

from __future__ import annotations

import os
import tempfile

import aiosqlite
import pytest

from src.migrate import Migration, MigrationError, get_current_version, run_migrations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    """Yield an in-memory aiosqlite connection, closed after test."""
    conn = await aiosqlite.connect(":memory:")
    yield conn
    await conn.close()


@pytest.fixture
async def file_db():
    """Yield a file-backed aiosqlite connection for persistence tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = await aiosqlite.connect(path)
    yield conn
    await conn.close()
    os.unlink(path)


SAMPLE_MIGRATIONS = (
    Migration(version=1, description="create items table",
              sql="CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)"),
    Migration(version=2, description="add price column",
              sql="ALTER TABLE items ADD COLUMN price REAL"),
)


# ---------------------------------------------------------------------------
# Tracking table creation
# ---------------------------------------------------------------------------

class TestTrackingTable:
    async def test_get_version_creates_tracking_table(self, db):
        """get_current_version auto-creates schema_migrations if missing."""
        version = await get_current_version(db)
        assert version == 0

    async def test_tracking_table_exists_after_run(self, db):
        """run_migrations creates tracking table even with empty migration list."""
        applied = await run_migrations(db, ())
        assert applied == 0
        # Table must exist
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )
        row = await cursor.fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# Applying migrations
# ---------------------------------------------------------------------------

class TestApplyMigrations:
    async def test_single_migration(self, db):
        """A single migration is applied and version advances."""
        migs = (SAMPLE_MIGRATIONS[0],)
        applied = await run_migrations(db, migs)
        assert applied == 1
        assert await get_current_version(db) == 1
        # Table must exist
        cursor = await db.execute("SELECT * FROM items")
        assert cursor.description is not None

    async def test_multiple_migrations_in_order(self, db):
        """Multiple migrations apply sequentially."""
        applied = await run_migrations(db, SAMPLE_MIGRATIONS)
        assert applied == 2
        assert await get_current_version(db) == 2
        # price column must exist
        await db.execute("INSERT INTO items (name, price) VALUES ('widget', 9.99)")

    async def test_records_version_description_timestamp(self, db):
        """Each applied migration records version, description, and applied_at."""
        await run_migrations(db, SAMPLE_MIGRATIONS)
        cursor = await db.execute(
            "SELECT version, description, applied_at FROM schema_migrations ORDER BY version"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 2
        assert rows[0][0] == 1
        assert rows[0][1] == "create items table"
        assert rows[0][2] is not None  # timestamp
        assert rows[1][0] == 2
        assert rows[1][1] == "add price column"

    async def test_multi_statement_sql(self, db):
        """SQL with multiple semicolon-separated statements works."""
        mig = Migration(
            version=1,
            description="multi-statement",
            sql="CREATE TABLE a (id INTEGER); CREATE TABLE b (id INTEGER)",
        )
        applied = await run_migrations(db, (mig,))
        assert applied == 1
        # Both tables exist
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('a','b') ORDER BY name"
        )
        rows = await cursor.fetchall()
        assert [r[0] for r in rows] == ["a", "b"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    async def test_skip_already_applied(self, db):
        """Re-running on an already-migrated DB applies 0."""
        await run_migrations(db, SAMPLE_MIGRATIONS)
        applied = await run_migrations(db, SAMPLE_MIGRATIONS)
        assert applied == 0
        assert await get_current_version(db) == 2

    async def test_applies_only_pending(self, db):
        """If DB is at v1, only v2+ migrations are applied."""
        await run_migrations(db, (SAMPLE_MIGRATIONS[0],))
        assert await get_current_version(db) == 1
        applied = await run_migrations(db, SAMPLE_MIGRATIONS)
        assert applied == 1
        assert await get_current_version(db) == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    async def test_bad_sql_raises_migration_error(self, db):
        """Invalid SQL raises MigrationError with version info."""
        mig = Migration(version=1, description="broken", sql="NOT VALID SQL")
        with pytest.raises(MigrationError) as exc_info:
            await run_migrations(db, (mig,))
        assert exc_info.value.version == 1
        assert exc_info.value.description == "broken"
        assert exc_info.value.cause is not None

    async def test_failed_migration_does_not_advance_version(self, db):
        """If a migration fails, the version stays at its previous value."""
        good = Migration(version=1, description="good",
                         sql="CREATE TABLE ok (id INTEGER)")
        bad = Migration(version=2, description="bad", sql="INVALID SQL HERE")
        with pytest.raises(MigrationError):
            await run_migrations(db, (good, bad))
        # Version should be 1 (good applied, bad failed)
        assert await get_current_version(db) == 1

    async def test_partial_failure_preserves_earlier(self, db):
        """Earlier successful migrations survive when a later one fails."""
        good = Migration(version=1, description="good",
                         sql="CREATE TABLE survived (id INTEGER)")
        bad = Migration(version=2, description="bad", sql="INVALID")
        with pytest.raises(MigrationError):
            await run_migrations(db, (good, bad))
        # Table from v1 still exists
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE name='survived'")
        assert await cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    async def test_duplicate_versions_raises(self, db):
        """Duplicate version numbers in the migration list raise ValueError."""
        migs = (
            Migration(version=1, description="first", sql="SELECT 1"),
            Migration(version=1, description="dupe", sql="SELECT 2"),
        )
        with pytest.raises(ValueError, match="[Dd]uplicate"):
            await run_migrations(db, migs)

    async def test_out_of_order_versions_raises(self, db):
        """Non-ascending versions raise ValueError."""
        migs = (
            Migration(version=2, description="second", sql="SELECT 1"),
            Migration(version=1, description="first", sql="SELECT 2"),
        )
        with pytest.raises(ValueError, match="[Aa]scending|[Oo]rder"):
            await run_migrations(db, migs)

    async def test_version_must_be_positive(self, db):
        """Version 0 or negative raises ValueError."""
        mig = Migration(version=0, description="bad", sql="SELECT 1")
        with pytest.raises(ValueError, match="[Pp]ositive"):
            await run_migrations(db, (mig,))
