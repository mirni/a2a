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

    async def connect(self) -> None:
        """Open the database connection and ensure schema exists."""
        try:
            from shared_src.db_security import harden_connection
        except ImportError:
            from src.db_security import harden_connection

        db_path = self.dsn.replace("sqlite:///", "")
        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
        await harden_connection(self._db)
        await asyncio.wait_for(
            self._db.executescript(self._SCHEMA),
            timeout=self._DB_TIMEOUT,
        )
        await self._db.commit()

        if self._MIGRATIONS:
            try:
                from shared_src.migrate import run_migrations
            except ImportError:
                from src.migrate import run_migrations
            await asyncio.wait_for(
                run_migrations(self._db, self._MIGRATIONS),
                timeout=self._DB_TIMEOUT,
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
            raise RuntimeError(
                f"{type(self).__name__} not connected. Call connect() first."
            )
        return self._db
