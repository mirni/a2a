"""SQLite storage layer for reputation pipeline probe targets.

Manages the probe_targets table that tracks which servers are registered
for continuous monitoring and their scheduling state. All database access
is async via aiosqlite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from .models import ProbeTarget

_SCHEMA = """
CREATE TABLE IF NOT EXISTS probe_targets (
    server_id       TEXT PRIMARY KEY,
    url             TEXT NOT NULL,
    probe_interval  REAL NOT NULL DEFAULT 300.0,
    scan_interval   REAL NOT NULL DEFAULT 3600.0,
    last_probed     REAL,
    last_scanned    REAL,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_target_active ON probe_targets(active);
"""


@dataclass
class ReputationStorage:
    """Async SQLite storage backend for probe target management."""

    dsn: str
    _db: aiosqlite.Connection | None = field(default=None, init=False, repr=False)

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
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ReputationStorage not connected. Call connect() first.")
        return self._db

    # -------------------------------------------------------------------
    # Probe target CRUD
    # -------------------------------------------------------------------

    async def add_target(self, target: ProbeTarget) -> ProbeTarget:
        """Insert or replace a probe target."""
        await self.db.execute(
            "INSERT OR REPLACE INTO probe_targets "
            "(server_id, url, probe_interval, scan_interval, last_probed, last_scanned, active) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                target.server_id,
                target.url,
                target.probe_interval,
                target.scan_interval,
                target.last_probed,
                target.last_scanned,
                int(target.active),
            ),
        )
        await self.db.commit()
        return target

    async def remove_target(self, server_id: str) -> bool:
        """Remove a probe target by server_id. Returns True if a row was deleted."""
        cursor = await self.db.execute(
            "DELETE FROM probe_targets WHERE server_id = ?", (server_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def deactivate_target(self, server_id: str) -> bool:
        """Soft-deactivate a target instead of deleting it."""
        cursor = await self.db.execute(
            "UPDATE probe_targets SET active = 0 WHERE server_id = ?", (server_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def activate_target(self, server_id: str) -> bool:
        """Re-activate a previously deactivated target."""
        cursor = await self.db.execute(
            "UPDATE probe_targets SET active = 1 WHERE server_id = ?", (server_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_target(self, server_id: str) -> ProbeTarget | None:
        """Retrieve a probe target by server_id."""
        cursor = await self.db.execute(
            "SELECT * FROM probe_targets WHERE server_id = ?", (server_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_target(row)

    async def list_targets(self, active_only: bool = True) -> list[ProbeTarget]:
        """List probe targets, optionally filtering to active ones only."""
        if active_only:
            cursor = await self.db.execute(
                "SELECT * FROM probe_targets WHERE active = 1 ORDER BY server_id"
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM probe_targets ORDER BY server_id"
            )
        rows = await cursor.fetchall()
        return [self._row_to_target(r) for r in rows]

    async def get_due_for_probe(self, now: float | None = None) -> list[ProbeTarget]:
        """Get active targets that are due for a health probe.

        A target is due if last_probed is NULL or
        (now - last_probed) >= probe_interval.
        """
        if now is None:
            now = time.time()
        cursor = await self.db.execute(
            "SELECT * FROM probe_targets WHERE active = 1 "
            "AND (last_probed IS NULL OR (? - last_probed) >= probe_interval) "
            "ORDER BY server_id",
            (now,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_target(r) for r in rows]

    async def get_due_for_scan(self, now: float | None = None) -> list[ProbeTarget]:
        """Get active targets that are due for a security scan.

        A target is due if last_scanned is NULL or
        (now - last_scanned) >= scan_interval.
        """
        if now is None:
            now = time.time()
        cursor = await self.db.execute(
            "SELECT * FROM probe_targets WHERE active = 1 "
            "AND (last_scanned IS NULL OR (? - last_scanned) >= scan_interval) "
            "ORDER BY server_id",
            (now,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_target(r) for r in rows]

    async def update_last_probed(self, server_id: str, timestamp: float) -> None:
        """Update the last_probed timestamp for a target."""
        await self.db.execute(
            "UPDATE probe_targets SET last_probed = ? WHERE server_id = ?",
            (timestamp, server_id),
        )
        await self.db.commit()

    async def update_last_scanned(self, server_id: str, timestamp: float) -> None:
        """Update the last_scanned timestamp for a target."""
        await self.db.execute(
            "UPDATE probe_targets SET last_scanned = ? WHERE server_id = ?",
            (timestamp, server_id),
        )
        await self.db.commit()

    async def update_intervals(
        self,
        server_id: str,
        probe_interval: float | None = None,
        scan_interval: float | None = None,
    ) -> bool:
        """Update probe and/or scan intervals for a target."""
        updates = []
        params: list[Any] = []
        if probe_interval is not None:
            updates.append("probe_interval = ?")
            params.append(probe_interval)
        if scan_interval is not None:
            updates.append("scan_interval = ?")
            params.append(scan_interval)
        if not updates:
            return False
        params.append(server_id)
        query = f"UPDATE probe_targets SET {', '.join(updates)} WHERE server_id = ?"
        cursor = await self.db.execute(query, params)
        await self.db.commit()
        return cursor.rowcount > 0

    async def count_targets(self, active_only: bool = True) -> int:
        """Count the number of probe targets."""
        if active_only:
            cursor = await self.db.execute(
                "SELECT COUNT(*) FROM probe_targets WHERE active = 1"
            )
        else:
            cursor = await self.db.execute("SELECT COUNT(*) FROM probe_targets")
        row = await cursor.fetchone()
        return row[0]

    # -------------------------------------------------------------------
    # Row conversion
    # -------------------------------------------------------------------

    @staticmethod
    def _row_to_target(row: aiosqlite.Row) -> ProbeTarget:
        return ProbeTarget(
            server_id=row["server_id"],
            url=row["url"],
            probe_interval=row["probe_interval"],
            scan_interval=row["scan_interval"],
            last_probed=row["last_probed"],
            last_scanned=row["last_scanned"],
            active=bool(row["active"]),
        )
