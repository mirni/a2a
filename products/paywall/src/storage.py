"""SQLite storage for API keys, tier mappings, and audit logs.

All database access is async via aiosqlite. Schema is auto-created on first connect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash   TEXT PRIMARY KEY,
    agent_id   TEXT NOT NULL,
    tier       TEXT NOT NULL,
    connector  TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_apikeys_agent ON api_keys(agent_id);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,
    connector  TEXT NOT NULL DEFAULT '',
    function   TEXT NOT NULL DEFAULT '',
    tier       TEXT NOT NULL DEFAULT '',
    cost       REAL NOT NULL DEFAULT 0.0,
    allowed    INTEGER NOT NULL DEFAULT 1,
    reason     TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_agent   ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

CREATE TABLE IF NOT EXISTS rate_windows (
    agent_id   TEXT NOT NULL,
    window_key TEXT NOT NULL,
    count      INTEGER NOT NULL DEFAULT 0,
    window_start REAL NOT NULL,
    PRIMARY KEY (agent_id, window_key)
);
"""


@dataclass
class PaywallStorage:
    """Async SQLite storage backend for the paywall layer."""

    dsn: str
    _db: aiosqlite.Connection | None = field(default=None, init=False, repr=False)

    async def connect(self) -> None:
        """Open the database connection and ensure schema exists."""
        db_path = self.dsn.replace("sqlite:///", "")
        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
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
            raise RuntimeError("PaywallStorage not connected. Call connect() first.")
        return self._db

    # -----------------------------------------------------------------------
    # API key operations
    # -----------------------------------------------------------------------

    async def store_key(
        self, key_hash: str, agent_id: str, tier: str, connector: str = ""
    ) -> dict[str, Any]:
        """Store a hashed API key."""
        now = time.time()
        await self.db.execute(
            "INSERT INTO api_keys (key_hash, agent_id, tier, connector, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (key_hash, agent_id, tier, connector, now),
        )
        await self.db.commit()
        return {
            "key_hash": key_hash,
            "agent_id": agent_id,
            "tier": tier,
            "connector": connector,
            "created_at": now,
            "revoked": 0,
        }

    async def lookup_key(self, key_hash: str) -> dict[str, Any] | None:
        """Look up an API key by its hash. Returns None if not found."""
        cursor = await self.db.execute(
            "SELECT key_hash, agent_id, tier, connector, created_at, revoked "
            "FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def revoke_key(self, key_hash: str) -> bool:
        """Revoke an API key. Returns True if found and revoked."""
        cursor = await self.db.execute(
            "UPDATE api_keys SET revoked = 1 WHERE key_hash = ? AND revoked = 0",
            (key_hash,),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_keys_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """Get all API keys for an agent."""
        cursor = await self.db.execute(
            "SELECT key_hash, agent_id, tier, connector, created_at, revoked "
            "FROM api_keys WHERE agent_id = ? ORDER BY created_at DESC",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Rate window operations (hourly sliding window)
    # -----------------------------------------------------------------------

    async def get_rate_count(self, agent_id: str, window_key: str, window_start: float) -> int:
        """Get the current call count for a rate window. Resets if window expired."""
        cursor = await self.db.execute(
            "SELECT count, window_start FROM rate_windows "
            "WHERE agent_id = ? AND window_key = ?",
            (agent_id, window_key),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0
        if row["window_start"] < window_start:
            # Window expired, reset
            await self.db.execute(
                "DELETE FROM rate_windows WHERE agent_id = ? AND window_key = ?",
                (agent_id, window_key),
            )
            await self.db.commit()
            return 0
        return row["count"]

    async def increment_rate_count(self, agent_id: str, window_key: str, window_start: float) -> int:
        """Increment rate counter, creating or resetting the window as needed. Returns new count."""
        cursor = await self.db.execute(
            "SELECT count, window_start FROM rate_windows "
            "WHERE agent_id = ? AND window_key = ?",
            (agent_id, window_key),
        )
        row = await cursor.fetchone()

        if row is None or row["window_start"] < window_start:
            # New window or expired
            await self.db.execute(
                "INSERT OR REPLACE INTO rate_windows (agent_id, window_key, count, window_start) "
                "VALUES (?, ?, 1, ?)",
                (agent_id, window_key, window_start),
            )
            await self.db.commit()
            return 1
        else:
            new_count = row["count"] + 1
            await self.db.execute(
                "UPDATE rate_windows SET count = ? WHERE agent_id = ? AND window_key = ?",
                (new_count, agent_id, window_key),
            )
            await self.db.commit()
            return new_count

    # -----------------------------------------------------------------------
    # Audit log operations
    # -----------------------------------------------------------------------

    async def record_audit(
        self,
        agent_id: str,
        connector: str = "",
        function: str = "",
        tier: str = "",
        cost: float = 0.0,
        allowed: bool = True,
        reason: str | None = None,
    ) -> int:
        """Record an audit log entry. Returns the row ID."""
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO audit_log (agent_id, connector, function, tier, cost, allowed, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, connector, function, tier, cost, 1 if allowed else 0, reason, now),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_audit_log(
        self,
        agent_id: str,
        since: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get audit log entries for an agent."""
        query = "SELECT * FROM audit_log WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_global_audit_log(
        self,
        since: float | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get audit log entries across all agents (admin global view)."""
        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def purge_audit_log(self, before: float) -> int:
        """Delete audit log entries older than the given timestamp. Returns count deleted."""
        cursor = await self.db.execute(
            "DELETE FROM audit_log WHERE created_at < ?", (before,)
        )
        await self.db.commit()
        return cursor.rowcount
