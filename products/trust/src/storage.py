"""SQLite storage layer for trust & reputation data.

All database access is async via aiosqlite. Schema is auto-created on first connect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from .models import ProbeResult, SecurityScan, Server, TransportType, TrustScore, Window

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    transport_type  TEXT NOT NULL DEFAULT 'http',
    registered_at   REAL NOT NULL,
    last_probed_at  REAL
);

CREATE TABLE IF NOT EXISTS probe_results (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id        TEXT NOT NULL,
    timestamp        REAL NOT NULL,
    latency_ms       REAL NOT NULL,
    status_code      INTEGER NOT NULL,
    error            TEXT,
    tools_count      INTEGER NOT NULL DEFAULT 0,
    tools_documented INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_probe_server ON probe_results(server_id);
CREATE INDEX IF NOT EXISTS idx_probe_ts     ON probe_results(timestamp);

CREATE TABLE IF NOT EXISTS security_scans (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id              TEXT NOT NULL,
    timestamp              REAL NOT NULL,
    tls_enabled            INTEGER NOT NULL DEFAULT 0,
    auth_required          INTEGER NOT NULL DEFAULT 0,
    input_validation_score REAL NOT NULL DEFAULT 0.0,
    cve_count              INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_scan_server ON security_scans(server_id);
CREATE INDEX IF NOT EXISTS idx_scan_ts     ON security_scans(timestamp);

CREATE TABLE IF NOT EXISTS trust_scores (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id            TEXT NOT NULL,
    timestamp            REAL NOT NULL,
    window               TEXT NOT NULL DEFAULT '24h',
    reliability_score    REAL NOT NULL DEFAULT 0.0,
    security_score       REAL NOT NULL DEFAULT 0.0,
    documentation_score  REAL NOT NULL DEFAULT 0.0,
    responsiveness_score REAL NOT NULL DEFAULT 0.0,
    composite_score      REAL NOT NULL DEFAULT 0.0,
    confidence           REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_score_server ON trust_scores(server_id);
CREATE INDEX IF NOT EXISTS idx_score_ts     ON trust_scores(timestamp);
CREATE INDEX IF NOT EXISTS idx_score_window ON trust_scores(server_id, window);
"""


@dataclass
class StorageBackend:
    """Async SQLite storage backend for all trust & reputation data."""

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
            raise RuntimeError("StorageBackend not connected. Call connect() first.")
        return self._db

    # -----------------------------------------------------------------------
    # Server operations
    # -----------------------------------------------------------------------

    async def register_server(self, server: Server) -> Server:
        """Insert a new server record."""
        await self.db.execute(
            "INSERT INTO servers (id, name, url, transport_type, registered_at, last_probed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (server.id, server.name, server.url, server.transport_type.value,
             server.registered_at, server.last_probed_at),
        )
        await self.db.commit()
        return server

    async def get_server(self, server_id: str) -> Server | None:
        """Retrieve a server by ID."""
        cursor = await self.db.execute(
            "SELECT * FROM servers WHERE id = ?", (server_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_server(row)

    async def update_server_last_probed(self, server_id: str, timestamp: float) -> None:
        """Update the last_probed_at timestamp for a server."""
        await self.db.execute(
            "UPDATE servers SET last_probed_at = ? WHERE id = ?",
            (timestamp, server_id),
        )
        await self.db.commit()

    async def list_servers(self) -> list[Server]:
        """List all registered servers."""
        cursor = await self.db.execute("SELECT * FROM servers ORDER BY registered_at DESC")
        rows = await cursor.fetchall()
        return [self._row_to_server(r) for r in rows]

    async def search_servers(
        self,
        name_contains: str | None = None,
        min_score: float | None = None,
        limit: int = 100,
    ) -> list[Server]:
        """Search servers by name or minimum composite score."""
        if min_score is not None:
            # Join with trust_scores to filter by score
            query = (
                "SELECT DISTINCT s.* FROM servers s "
                "INNER JOIN trust_scores ts ON s.id = ts.server_id "
                "WHERE ts.composite_score >= ?"
            )
            params: list[Any] = [min_score]
            if name_contains:
                query += " AND s.name LIKE ?"
                params.append(f"%{name_contains}%")
            query += " ORDER BY s.registered_at DESC LIMIT ?"
            params.append(limit)
        else:
            query = "SELECT * FROM servers WHERE 1=1"
            params = []
            if name_contains:
                query += " AND name LIKE ?"
                params.append(f"%{name_contains}%")
            query += " ORDER BY registered_at DESC LIMIT ?"
            params.append(limit)

        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_server(r) for r in rows]

    async def delete_server(self, server_id: str) -> bool:
        """Delete a server and all associated data (probes, scans, scores).

        Returns True if the server existed and was deleted.
        """
        cursor = await self.db.execute(
            "DELETE FROM servers WHERE id = ?", (server_id,)
        )
        if cursor.rowcount == 0:
            return False
        await self.db.execute(
            "DELETE FROM probe_results WHERE server_id = ?", (server_id,)
        )
        await self.db.execute(
            "DELETE FROM security_scans WHERE server_id = ?", (server_id,)
        )
        await self.db.execute(
            "DELETE FROM trust_scores WHERE server_id = ?", (server_id,)
        )
        await self.db.commit()
        return True

    async def update_server(
        self, server_id: str, name: str | None = None, url: str | None = None
    ) -> Server | None:
        """Update a server's name and/or url. Returns updated Server or None if not found."""
        existing = await self.get_server(server_id)
        if existing is None:
            return None

        updates: list[str] = []
        values: list[Any] = []
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if url is not None:
            updates.append("url = ?")
            values.append(url)

        if updates:
            values.append(server_id)
            await self.db.execute(
                f"UPDATE servers SET {', '.join(updates)} WHERE id = ?",
                values,
            )
            await self.db.commit()

        return await self.get_server(server_id)

    # -----------------------------------------------------------------------
    # Probe results
    # -----------------------------------------------------------------------

    async def store_probe_result(self, probe: ProbeResult) -> int:
        """Store a probe result and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO probe_results "
            "(server_id, timestamp, latency_ms, status_code, error, tools_count, tools_documented) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (probe.server_id, probe.timestamp, probe.latency_ms,
             probe.status_code, probe.error, probe.tools_count, probe.tools_documented),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_probe_results(
        self,
        server_id: str,
        since: float | None = None,
        limit: int = 1000,
    ) -> list[ProbeResult]:
        """Retrieve probe results for a server, optionally filtered by time."""
        query = "SELECT * FROM probe_results WHERE server_id = ?"
        params: list[Any] = [server_id]
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            ProbeResult(
                server_id=r["server_id"],
                timestamp=r["timestamp"],
                latency_ms=r["latency_ms"],
                status_code=r["status_code"],
                error=r["error"],
                tools_count=r["tools_count"],
                tools_documented=r["tools_documented"],
            )
            for r in rows
        ]

    async def get_latest_probe(self, server_id: str) -> ProbeResult | None:
        """Retrieve the most recent probe result for a server."""
        cursor = await self.db.execute(
            "SELECT * FROM probe_results WHERE server_id = ? ORDER BY timestamp DESC LIMIT 1",
            (server_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return ProbeResult(
            server_id=row["server_id"],
            timestamp=row["timestamp"],
            latency_ms=row["latency_ms"],
            status_code=row["status_code"],
            error=row["error"],
            tools_count=row["tools_count"],
            tools_documented=row["tools_documented"],
        )

    # -----------------------------------------------------------------------
    # Security scans
    # -----------------------------------------------------------------------

    async def store_security_scan(self, scan: SecurityScan) -> int:
        """Store a security scan result and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO security_scans "
            "(server_id, timestamp, tls_enabled, auth_required, input_validation_score, cve_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (scan.server_id, scan.timestamp, int(scan.tls_enabled),
             int(scan.auth_required), scan.input_validation_score, scan.cve_count),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_security_scans(
        self,
        server_id: str,
        since: float | None = None,
        limit: int = 100,
    ) -> list[SecurityScan]:
        """Retrieve security scans for a server."""
        query = "SELECT * FROM security_scans WHERE server_id = ?"
        params: list[Any] = [server_id]
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [
            SecurityScan(
                server_id=r["server_id"],
                timestamp=r["timestamp"],
                tls_enabled=bool(r["tls_enabled"]),
                auth_required=bool(r["auth_required"]),
                input_validation_score=r["input_validation_score"],
                cve_count=r["cve_count"],
            )
            for r in rows
        ]

    async def get_latest_security_scan(self, server_id: str) -> SecurityScan | None:
        """Retrieve the most recent security scan for a server."""
        cursor = await self.db.execute(
            "SELECT * FROM security_scans WHERE server_id = ? ORDER BY timestamp DESC LIMIT 1",
            (server_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SecurityScan(
            server_id=row["server_id"],
            timestamp=row["timestamp"],
            tls_enabled=bool(row["tls_enabled"]),
            auth_required=bool(row["auth_required"]),
            input_validation_score=row["input_validation_score"],
            cve_count=row["cve_count"],
        )

    # -----------------------------------------------------------------------
    # Trust scores
    # -----------------------------------------------------------------------

    async def store_trust_score(self, score: TrustScore) -> int:
        """Store a computed trust score and return its row ID."""
        cursor = await self.db.execute(
            "INSERT INTO trust_scores "
            "(server_id, timestamp, window, reliability_score, security_score, "
            "documentation_score, responsiveness_score, composite_score, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (score.server_id, score.timestamp, score.window.value,
             score.reliability_score, score.security_score,
             score.documentation_score, score.responsiveness_score,
             score.composite_score, score.confidence),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_latest_trust_score(
        self, server_id: str, window: Window = Window.H24
    ) -> TrustScore | None:
        """Retrieve the most recent trust score for a server and window."""
        cursor = await self.db.execute(
            "SELECT * FROM trust_scores WHERE server_id = ? AND window = ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (server_id, window.value),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_trust_score(row)

    async def get_score_history(
        self,
        server_id: str,
        window: Window = Window.H24,
        since: float | None = None,
        limit: int = 100,
    ) -> list[TrustScore]:
        """Retrieve trust score history for a server."""
        query = "SELECT * FROM trust_scores WHERE server_id = ? AND window = ?"
        params: list[Any] = [server_id, window.value]
        if since is not None:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._row_to_trust_score(r) for r in rows]

    # -----------------------------------------------------------------------
    # Row conversion helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _row_to_server(row: aiosqlite.Row) -> Server:
        return Server(
            id=row["id"],
            name=row["name"],
            url=row["url"],
            transport_type=TransportType(row["transport_type"]),
            registered_at=row["registered_at"],
            last_probed_at=row["last_probed_at"],
        )

    @staticmethod
    def _row_to_trust_score(row: aiosqlite.Row) -> TrustScore:
        return TrustScore(
            server_id=row["server_id"],
            timestamp=row["timestamp"],
            window=Window(row["window"]),
            reliability_score=row["reliability_score"],
            security_score=row["security_score"],
            documentation_score=row["documentation_score"],
            responsiveness_score=row["responsiveness_score"],
            composite_score=row["composite_score"],
            confidence=row["confidence"],
        )
