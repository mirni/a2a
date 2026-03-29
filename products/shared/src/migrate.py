"""Schema migration runner for SQLite storage backends.

Provides sequential, version-tracked migrations so that schema changes
(ALTER TABLE, new indexes, etc.) are applied exactly once on each database.
"""

from __future__ import annotations

import time
from typing import NamedTuple, Sequence

import aiosqlite


class Migration(NamedTuple):
    """A single schema migration step."""

    version: int  # Sequential, 1-based
    description: str  # Human-readable label
    sql: str  # SQL to execute (may contain multiple semicolon-separated statements)


class MigrationError(Exception):
    """Raised when a migration fails to apply."""

    def __init__(self, version: int, description: str, cause: Exception) -> None:
        self.version = version
        self.description = description
        self.cause = cause
        super().__init__(
            f"Migration v{version} ({description}) failed: {cause}"
        )


_TRACKING_DDL = """\
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  REAL NOT NULL
);
"""


async def _ensure_tracking_table(db: aiosqlite.Connection) -> None:
    """Create the schema_migrations table if it doesn't exist."""
    await db.executescript(_TRACKING_DDL)


async def get_current_version(db: aiosqlite.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    await _ensure_tracking_table(db)
    cursor = await db.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


def _validate_migrations(migrations: Sequence[Migration]) -> None:
    """Raise ValueError if migrations have invalid versions."""
    versions = [m.version for m in migrations]
    for v in versions:
        if v < 1:
            raise ValueError(f"Migration versions must be positive, got {v}")
    if len(versions) != len(set(versions)):
        raise ValueError(f"Duplicate migration versions: {versions}")
    if versions != sorted(versions):
        raise ValueError(
            f"Migration versions must be in ascending order: {versions}"
        )


async def run_migrations(
    db: aiosqlite.Connection,
    migrations: Sequence[Migration],
) -> int:
    """Apply pending migrations to *db* and return the count applied.

    Each migration runs in its own transaction. On failure the current
    migration is rolled back, a ``MigrationError`` is raised, and all
    previously-applied migrations in this call are preserved.
    """
    _validate_migrations(migrations)
    await _ensure_tracking_table(db)

    current = await get_current_version(db)
    applied = 0

    for mig in migrations:
        if mig.version <= current:
            continue

        try:
            await db.execute("BEGIN")
            await db.executescript(mig.sql)
            await db.execute(
                "INSERT INTO schema_migrations (version, description, applied_at) "
                "VALUES (?, ?, ?)",
                (mig.version, mig.description, time.time()),
            )
            await db.commit()
            applied += 1
        except Exception as exc:
            try:
                await db.rollback()
            except Exception:
                pass  # rollback best-effort; executescript may auto-commit
            raise MigrationError(mig.version, mig.description, exc) from exc

    return applied
