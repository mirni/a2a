"""Cross-product event bus with SHA-3 integrity hashing.

Provides pub/sub messaging across A2A commerce products with:
- SQLite-backed persistence
- SHA-3-256 integrity hashing for tamper detection
- Filtered subscriptions
- Event replay from offset
- Acknowledgment tracking
- Automatic cleanup of expired events
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

logger = logging.getLogger("a2a.event_bus")


@dataclass
class EventBus:
    """SQLite-backed event bus with SHA-3 integrity hashing.

    Attributes:
        dsn: SQLite connection string (e.g. ``sqlite:///path/to/db``).
    """

    dsn: str
    _db: aiosqlite.Connection | None = field(default=None, init=False, repr=False)
    _subscribers: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    @property
    def db(self) -> aiosqlite.Connection:
        """Public accessor for the database connection."""
        return self._require_db()

    def _require_db(self) -> aiosqlite.Connection:
        """Return the database connection, raising RuntimeError if not connected."""
        if self._db is None:
            raise RuntimeError("EventBus not connected — call connect() first")
        return self._db

    @property
    def _db_path(self) -> str:
        return self.dsn.replace("sqlite:///", "")

    async def connect(self) -> None:
        """Open the database and create tables if needed."""
        try:
            from shared_src.db_security import harden_connection
        except ImportError:
            from src.db_security import harden_connection

        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await harden_connection(self._db)
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT    NOT NULL,
                source      TEXT    NOT NULL,
                payload     TEXT    NOT NULL,
                integrity_hash TEXT NOT NULL,
                created_at  TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_type_id
                ON events (event_type, id);

            CREATE TABLE IF NOT EXISTS subscriptions (
                id          TEXT PRIMARY KEY,
                event_type  TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                last_ack_id INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    async def publish(self, event_type: str, source: str, payload: dict) -> int:
        """Persist an event and dispatch to matching subscribers.

        Computes a SHA-3-256 hash of (event_type + source + json(payload) + timestamp)
        and stores it alongside the event for integrity verification.

        Returns:
            The auto-generated event ID.
        """
        self._require_db()

        created_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        payload_json = json.dumps(payload, sort_keys=True)
        raw = event_type + source + payload_json + created_at
        integrity_hash = hashlib.sha3_256(raw.encode()).hexdigest()

        cursor = await self._db.execute(
            """
            INSERT INTO events (event_type, source, payload, integrity_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_type, source, payload_json, integrity_hash, created_at),
        )
        await self._db.commit()
        event_id = cursor.lastrowid
        if event_id is None:
            raise RuntimeError("Failed to insert event")

        # Build event dict for handlers
        event = {
            "id": event_id,
            "event_type": event_type,
            "source": source,
            "payload": payload,
            "integrity_hash": integrity_hash,
            "created_at": created_at,
        }

        # Dispatch to matching subscribers
        await self._dispatch(event)

        return event_id

    # ------------------------------------------------------------------
    # Subscribe / Unsubscribe
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        event_type: str,
        handler: Callable,
        filter_fn: Callable | None = None,
    ) -> str:
        """Register a handler for an event type.

        Args:
            event_type: The event type to listen for.
            handler: Async callable that receives the event dict.
            filter_fn: Optional sync predicate; if it returns False, the
                       handler is not invoked.

        Returns:
            A unique subscription ID.
        """
        self._require_db()

        sub_id = uuid.uuid4().hex
        created_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

        await self._db.execute(
            """
            INSERT INTO subscriptions (id, event_type, created_at, last_ack_id)
            VALUES (?, ?, ?, 0)
            """,
            (sub_id, event_type, created_at),
        )
        await self._db.commit()

        self._subscribers[sub_id] = {
            "event_type": event_type,
            "handler": handler,
            "filter_fn": filter_fn,
        }

        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription."""
        self._require_db()

        self._subscribers.pop(subscription_id, None)

        await self._db.execute("DELETE FROM subscriptions WHERE id = ?", (subscription_id,))
        await self._db.commit()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def get_events(
        self,
        event_type: str | None = None,
        since_id: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve events, optionally filtered by type and offset.

        Args:
            event_type: If given, only return events of this type.
            since_id: Only return events with id > since_id.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts in FIFO (ascending id) order.
        """
        self._require_db()

        if event_type is not None:
            cursor = await self._db.execute(
                """
                SELECT id, event_type, source, payload, integrity_hash, created_at
                FROM events
                WHERE event_type = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (event_type, since_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT id, event_type, source, payload, integrity_hash, created_at
                FROM events
                WHERE id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (since_id, limit),
            )

        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Integrity verification
    # ------------------------------------------------------------------

    async def verify_integrity(self, event_id: int) -> bool:
        """Recompute SHA-3-256 hash and compare with stored hash.

        Returns:
            True if the event has not been tampered with.
        """
        self._require_db()

        cursor = await self._db.execute(
            """
            SELECT event_type, source, payload, integrity_hash, created_at
            FROM events
            WHERE id = ?
            """,
            (event_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return False

        raw = row["event_type"] + row["source"] + row["payload"] + row["created_at"]
        expected = hashlib.sha3_256(raw.encode()).hexdigest()
        return expected == row["integrity_hash"]

    # ------------------------------------------------------------------
    # Acknowledgment
    # ------------------------------------------------------------------

    async def acknowledge(self, subscription_id: str, event_id: int) -> None:
        """Mark an event as acknowledged for a subscription.

        Updates the subscription's last_ack_id so consumers can track
        their position in the event stream.
        """
        self._require_db()

        await self._db.execute(
            "UPDATE subscriptions SET last_ack_id = ? WHERE id = ?",
            (event_id, subscription_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup(self, older_than_seconds: float) -> int:
        """Delete events older than the given threshold.

        Args:
            older_than_seconds: Delete events created more than this many
                seconds ago.

        Returns:
            Number of events deleted.
        """
        self._require_db()

        cutoff = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - older_than_seconds))
        cursor = await self._db.execute("DELETE FROM events WHERE created_at <= ?", (cutoff,))
        await self._db.commit()
        return cursor.rowcount

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _dispatch(self, event: dict) -> None:
        """Dispatch an event to all matching in-memory subscribers."""
        tasks = []
        for sub_info in self._subscribers.values():
            if sub_info["event_type"] != event["event_type"]:
                continue
            filter_fn = sub_info["filter_fn"]
            if filter_fn is not None and not filter_fn(event):
                continue
            tasks.append(sub_info["handler"](event))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("Event handler failed: %s", r, exc_info=r)

    @staticmethod
    def _row_to_dict(row: aiosqlite.Row) -> dict:
        """Convert an aiosqlite Row to a plain dict with parsed payload."""
        return {
            "id": row["id"],
            "event_type": row["event_type"],
            "source": row["source"],
            "payload": json.loads(row["payload"]),
            "integrity_hash": row["integrity_hash"],
            "created_at": row["created_at"],
        }
