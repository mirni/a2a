"""Base SQLite storage backend — eliminates boilerplate across product modules.

All product storage classes can inherit from BaseStorage to get:
- connect()/close() lifecycle
- db property with null guard
- Schema auto-creation on connect
- Connection hardening via shared db_security
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import aiosqlite


@dataclass
class BaseStorage:
    """Async SQLite storage with common lifecycle boilerplate.

    Subclasses set ``_SCHEMA`` as a class variable containing the SQL DDL.
    """

    dsn: str
    _db: aiosqlite.Connection | None = field(default=None, init=False, repr=False)

    # Subclasses override with their CREATE TABLE statements
    _SCHEMA: str = ""

    # Subclasses override with a tuple of Migration objects for schema changes
    _MIGRATIONS: tuple = ()

    # Timeout in seconds for DB operations (schema creation, migrations)
    _DB_TIMEOUT: float = 5.0

    # Subclasses can override to use explicit transaction management.
    # None = autocommit (callers must use BEGIN/COMMIT explicitly for atomicity).
    # "" = deferred implicit transactions (default aiosqlite behavior).
    _ISOLATION_LEVEL: str | None = ""

    async def connect(self, *, apply_migrations: bool = False) -> None:
        """Open the database connection and ensure schema exists.

        If *apply_migrations* is True, pending migrations are applied (for
        tests and the migration script).  Otherwise, the schema version is
        checked and ``SchemaVersionMismatchError`` is raised on mismatch.
        """
        try:
            from shared_src.db_security import harden_connection
        except ImportError:
            from src.db_security import harden_connection

        db_path = self.dsn.replace("sqlite:///", "")
        self._db = await aiosqlite.connect(db_path, isolation_level=self._ISOLATION_LEVEL)
        self._db.row_factory = aiosqlite.Row
        await harden_connection(self._db)

        # Detect whether this is a pre-existing DB (has user tables) before
        # running DDL, so we can distinguish "fresh" from "old schema".
        cursor = await self._db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        row = await cursor.fetchone()
        is_fresh_db = row[0] == 0

        try:
            await asyncio.wait_for(
                self._db.executescript(self._SCHEMA),
                timeout=self._DB_TIMEOUT,
            )
            await self._db.commit()
        except Exception:
            # Schema DDL may fail on old DBs (e.g. index on a column that
            # hasn't been added by migration yet).  Fall through to version
            # check which will produce a clear error.
            if not self._MIGRATIONS:
                raise

        if self._MIGRATIONS:
            try:
                from shared_src.migrate import (
                    _ensure_tracking_table,
                    check_schema_version,
                    get_current_version,
                    run_migrations,
                )
            except ImportError:
                from src.migrate import (
                    _ensure_tracking_table,
                    check_schema_version,
                    get_current_version,
                    run_migrations,
                )

            if is_fresh_db:
                # Fresh DB: _SCHEMA already includes the full current DDL.
                # Stamp the max migration version so run_migrations() skips.
                import time as _time

                max(m.version for m in self._MIGRATIONS)
                await _ensure_tracking_table(self._db)
                current = await get_current_version(self._db)
                if current == 0:
                    for m in self._MIGRATIONS:
                        await self._db.execute(
                            "INSERT INTO schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
                            (m.version, m.description, _time.time()),
                        )
                    await self._db.commit()

            if apply_migrations:
                await asyncio.wait_for(
                    run_migrations(self._db, self._MIGRATIONS),
                    timeout=self._DB_TIMEOUT,
                )
            else:
                expected = max(m.version for m in self._MIGRATIONS)
                await check_schema_version(
                    self._db,
                    expected,
                    type(self).__name__,
                    allow_fresh=is_fresh_db,
                )

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        """Return the active database connection or raise if not connected."""
        if self._db is None:
            raise RuntimeError(f"{type(self).__name__} not connected. Call connect() first.")
        return self._db
