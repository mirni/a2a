"""Shared column-migration helper for product storage backends.

Audit finding C2 (v1.0.1 external audit, PR #61) was that
``PaymentStorage.connect()`` called ``executescript(_SCHEMA)`` on
already-existing databases whose tables pre-dated newer columns. The
``CREATE TABLE IF NOT EXISTS`` statements were no-ops against those
tables, but ``CREATE INDEX ... ON settlements(source_type, source_id)``
was **not** a no-op — it referenced columns that didn't exist, and the
script aborted with ``OperationalError: no such column: source_type``.
Result: 100% capture failure on every production DB created by an
older code version.

PR #61 fixed payments by adding a bespoke ``_apply_column_migrations``
method. Every other storage backend (identity, messaging, trust,
marketplace, paywall) still has the same class of vulnerability
waiting to be triggered the day a column is added — there is nothing
structural forcing a future contributor to register the migration.

This module is that structure. It exposes a single helper,
:func:`apply_column_migrations`, that every storage backend's
``connect()`` method must call **before** running its DDL script. The
helper is a no-op if the migration list is empty, so new modules can
wire in the hook immediately and populate it only when needed.

Usage::

    from shared_src.storage_migrations import apply_column_migrations

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(...)
        # Hook point. Register new columns HERE, before executescript.
        await apply_column_migrations(
            self._db,
            [
                ("agents", "org_id", "TEXT NOT NULL DEFAULT ''"),
            ],
        )
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
"""

from __future__ import annotations

from collections.abc import Sequence

import aiosqlite

Migration = tuple[str, str, str]  # (table, column, column_sql_type)


async def apply_column_migrations(
    db: aiosqlite.Connection,
    migrations: Sequence[Migration],
) -> None:
    """Add missing columns to existing tables idempotently.

    Each migration is a ``(table, column, col_type)`` triple. For every
    entry the helper checks ``PRAGMA table_info`` and only runs
    ``ALTER TABLE ... ADD COLUMN`` when the column is absent. Tables
    that do not yet exist are skipped silently — the caller's
    subsequent ``executescript(_SCHEMA)`` will create them fresh with
    the full current schema.

    Safe to call with an empty list.
    """
    if not migrations:
        return

    altered = False
    for table, column, col_type in migrations:
        cursor = await db.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
            f"PRAGMA table_info({table})"
        )
        rows = await cursor.fetchall()
        if not rows:
            # Table doesn't exist yet — let executescript(_SCHEMA) create it.
            continue
        columns = {row[1] for row in rows}
        if column in columns:
            continue
        await db.execute(  # nosemgrep: formatted-sql-query, sqlalchemy-execute-raw-query
            f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
        )
        altered = True

    if altered:
        await db.commit()
