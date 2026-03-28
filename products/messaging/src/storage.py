"""SQLite storage layer for the agent-to-agent messaging system.

All database access is async via aiosqlite. Schema is auto-created on first connect.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiosqlite

from .models import Message

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id           TEXT PRIMARY KEY,
    sender       TEXT NOT NULL,
    recipient    TEXT NOT NULL,
    message_type TEXT NOT NULL,
    subject      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    metadata     TEXT NOT NULL DEFAULT '{}',
    thread_id    TEXT,
    created_at   REAL NOT NULL,
    read_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_messages_sender    ON messages(sender);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient);
CREATE INDEX IF NOT EXISTS idx_messages_thread    ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_created   ON messages(created_at);

CREATE TABLE IF NOT EXISTS negotiations (
    id              TEXT PRIMARY KEY,
    thread_id       TEXT NOT NULL,
    initiator       TEXT NOT NULL,
    responder       TEXT NOT NULL,
    proposed_amount REAL NOT NULL,
    current_amount  REAL NOT NULL,
    status          TEXT NOT NULL,
    service_id      TEXT NOT NULL DEFAULT '',
    expires_at      REAL,
    created_at      REAL NOT NULL,
    updated_at      REAL
);

CREATE INDEX IF NOT EXISTS idx_negotiations_thread    ON negotiations(thread_id);
CREATE INDEX IF NOT EXISTS idx_negotiations_initiator ON negotiations(initiator);
CREATE INDEX IF NOT EXISTS idx_negotiations_responder ON negotiations(responder);
CREATE INDEX IF NOT EXISTS idx_negotiations_status    ON negotiations(status);
"""


def _parse_dsn(dsn: str) -> str:
    """Extract the file path from a sqlite:/// DSN string."""
    prefix = "sqlite:///"
    if dsn.startswith(prefix):
        return dsn[len(prefix):]
    return dsn


class MessageStorage:
    """Async SQLite storage for messages and negotiations."""

    def __init__(self, dsn: str = "sqlite:///messaging.db") -> None:
        self._db_path = _parse_dsn(dsn)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database connection and ensure schema exists."""
        try:
            from shared_src.db_security import harden_connection
        except ImportError:
            from src.db_security import harden_connection

        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await harden_connection(self._db)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    def _require_db(self) -> aiosqlite.Connection:
        """Return the database connection, raising RuntimeError if not connected."""
        if self._db is None:
            raise RuntimeError("MessageStorage not connected — call connect() first")
        return self._db

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def store_message(self, message: Message) -> str:
        """Store a message and return its id."""
        self._require_db()
        await self._db.execute(
            """
            INSERT INTO messages (id, sender, recipient, message_type, subject, body, metadata, thread_id, created_at, read_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.sender,
                message.recipient,
                message.message_type.value if hasattr(message.message_type, "value") else message.message_type,
                message.subject,
                message.body,
                json.dumps(message.metadata),
                message.thread_id,
                message.created_at,
                message.read_at,
            ),
        )
        await self._db.commit()
        return message.id

    async def get_messages(
        self,
        agent_id: str,
        thread_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get messages where agent_id is sender or recipient, newest first.

        If thread_id is provided, filter to that thread only.
        """
        self._require_db()
        if thread_id is not None:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE (sender = ? OR recipient = ?) AND thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, agent_id, thread_id, limit),
            )
        else:
            cursor = await self._db.execute(
                """
                SELECT * FROM messages
                WHERE sender = ? OR recipient = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, agent_id, limit),
            )
        rows = await cursor.fetchall()
        return [self._row_to_message_dict(row) for row in rows]

    async def get_thread(self, thread_id: str) -> list[dict]:
        """Get all messages in a thread, ordered oldest first."""
        self._require_db()
        cursor = await self._db.execute(
            """
            SELECT * FROM messages
            WHERE thread_id = ?
            ORDER BY created_at ASC
            """,
            (thread_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_message_dict(row) for row in rows]

    async def mark_read(self, message_id: str, agent_id: str) -> bool:
        """Mark a message as read. Only the recipient can mark it.

        Returns True if the message was found and the agent is the recipient.
        """
        self._require_db()
        now = time.time()
        cursor = await self._db.execute(
            """
            UPDATE messages SET read_at = ?
            WHERE id = ? AND recipient = ? AND read_at IS NULL
            """,
            (now, message_id, agent_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Negotiations
    # ------------------------------------------------------------------

    async def store_negotiation(self, data: dict) -> str:
        """Store a negotiation record and return its id."""
        self._require_db()
        neg_id = uuid.uuid4().hex
        now = time.time()
        await self._db.execute(
            """
            INSERT INTO negotiations (id, thread_id, initiator, responder, proposed_amount, current_amount, status, service_id, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                neg_id,
                data["thread_id"],
                data["initiator"],
                data["responder"],
                data["proposed_amount"],
                data["current_amount"],
                data["status"],
                data.get("service_id", ""),
                data.get("expires_at"),
                now,
                now,
            ),
        )
        await self._db.commit()
        return neg_id

    async def get_negotiation(self, negotiation_id: str) -> dict | None:
        """Retrieve a negotiation by id. Returns None if not found."""
        self._require_db()
        cursor = await self._db.execute(
            "SELECT * FROM negotiations WHERE id = ?",
            (negotiation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_negotiation_dict(row)

    _NEGOTIATION_COLUMNS = frozenset({
        "current_amount", "status", "counter_party_id",
        "expires_at", "updated_at", "metadata",
    })

    async def update_negotiation(self, negotiation_id: str, updates: dict) -> None:
        """Update specific fields of a negotiation.

        Only columns in _NEGOTIATION_COLUMNS are allowed to prevent SQL injection
        via dynamic column names.
        """
        self._require_db()
        updates["updated_at"] = time.time()
        invalid = set(updates.keys()) - self._NEGOTIATION_COLUMNS
        if invalid:
            raise ValueError(f"Invalid negotiation columns: {invalid}")
        set_clauses = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [negotiation_id]
        await self._db.execute(
            f"UPDATE negotiations SET {set_clauses} WHERE id = ?",
            values,
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_message_dict(row: aiosqlite.Row) -> dict:
        """Convert a sqlite Row to a plain dict with parsed metadata."""
        d = dict(row)
        if isinstance(d.get("metadata"), str):
            d["metadata"] = json.loads(d["metadata"])
        return d

    @staticmethod
    def _row_to_negotiation_dict(row: aiosqlite.Row) -> dict:
        """Convert a sqlite Row to a plain dict."""
        return dict(row)
