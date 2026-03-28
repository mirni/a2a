"""Webhook management with SQLite-backed storage and async delivery."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any

import aiosqlite
import httpx

_SCHEMA_WEBHOOKS = """
CREATE TABLE IF NOT EXISTS webhooks (
    id          TEXT PRIMARY KEY,
    agent_id    TEXT    NOT NULL,
    url         TEXT    NOT NULL,
    event_types TEXT    NOT NULL,  -- JSON array
    secret      TEXT    NOT NULL,
    created_at  REAL    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1
);
"""

_SCHEMA_DELIVERIES = """
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id      TEXT    NOT NULL,
    event_type      TEXT    NOT NULL,
    payload         TEXT    NOT NULL,  -- JSON
    status          TEXT    NOT NULL DEFAULT 'pending',
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at REAL,
    next_retry_at   REAL,
    response_code   INTEGER,
    response_body   TEXT,
    created_at      REAL    NOT NULL,
    FOREIGN KEY (webhook_id) REFERENCES webhooks(id)
);
"""

_MAX_ATTEMPTS = 3
_BASE_DELAY = 10  # seconds
_EXPONENTIAL_BASE = 2


class WebhookManager:
    """Manages webhook registrations, delivery, and retries via SQLite."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._db: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the database connection and create the schema."""
        from shared_src.db_security import harden_connection

        db_path = self._dsn.replace("sqlite:///", "")
        self._db = await aiosqlite.connect(db_path)
        self._db.row_factory = aiosqlite.Row
        await harden_connection(self._db)
        await self._db.execute(_SCHEMA_WEBHOOKS)
        await self._db.execute(_SCHEMA_DELIVERIES)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(
        self,
        agent_id: str,
        url: str,
        event_types: list[str],
        secret: str,
    ) -> dict[str, Any]:
        """Register a new webhook and return its representation."""
        assert self._db is not None, "call connect() first"

        webhook_id = f"whk-{secrets.token_hex(12)}"
        created_at = time.time()
        event_types_json = json.dumps(event_types)

        await self._db.execute(
            """
            INSERT INTO webhooks (id, agent_id, url, event_types, secret, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (webhook_id, agent_id, url, event_types_json, secret, created_at),
        )
        await self._db.commit()

        return {
            "id": webhook_id,
            "agent_id": agent_id,
            "url": url,
            "event_types": event_types,
            "secret": secret,
            "created_at": created_at,
            "active": 1,
        }

    async def list_webhooks(self, agent_id: str) -> list[dict[str, Any]]:
        """Return all webhooks belonging to *agent_id*."""
        assert self._db is not None, "call connect() first"

        cursor = await self._db.execute(
            "SELECT * FROM webhooks WHERE agent_id = ? AND active = 1",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_webhook(row) for row in rows]

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Soft-delete a webhook. Returns True if it existed and was active."""
        assert self._db is not None, "call connect() first"

        cursor = await self._db.execute(
            "UPDATE webhooks SET active = 0 WHERE id = ? AND active = 1",
            (webhook_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    async def deliver(self, event: dict[str, Any]) -> None:
        """Queue delivery records for every active webhook matching *event_type*."""
        assert self._db is not None, "call connect() first"

        event_type = event.get("type", "")
        now = time.time()
        payload_json = json.dumps(event)

        cursor = await self._db.execute(
            "SELECT * FROM webhooks WHERE active = 1",
        )
        webhooks = await cursor.fetchall()

        for row in webhooks:
            registered_types: list[str] = json.loads(row["event_types"])
            if event_type not in registered_types:
                continue

            webhook = self._row_to_webhook(row)
            delivery_id = await self._insert_delivery(
                webhook_id=webhook["id"],
                event_type=event_type,
                payload_json=payload_json,
                now=now,
            )
            await self._send(webhook, delivery_id, event)

    async def _send(
        self,
        webhook: dict[str, Any],
        delivery_id: int,
        event: dict[str, Any],
    ) -> None:
        """POST the event payload to the webhook URL with HMAC-SHA3 signature."""
        assert self._db is not None, "call connect() first"

        payload_bytes = json.dumps(event).encode()
        signature = hmac.new(
            webhook["secret"].encode(),
            payload_bytes,
            hashlib.sha3_256,
        ).hexdigest()

        now = time.time()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    webhook["url"],
                    content=payload_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-A2A-Signature": signature,
                    },
                )
            status_code = response.status_code
            body = response.text
            success = 200 <= status_code < 300
        except httpx.HTTPError as exc:
            status_code = None
            body = str(exc)
            success = False

        # Read current attempt count so we can decide the next state.
        cursor = await self._db.execute(
            "SELECT attempts FROM webhook_deliveries WHERE id = ?",
            (delivery_id,),
        )
        row = await cursor.fetchone()
        attempts = (row["attempts"] if row else 0) + 1

        if success:
            new_status = "delivered"
            next_retry_at = None
        elif attempts >= _MAX_ATTEMPTS:
            new_status = "failed"
            next_retry_at = None
        else:
            new_status = "pending"
            delay = _BASE_DELAY * (_EXPONENTIAL_BASE ** (attempts - 1))
            next_retry_at = now + delay

        await self._db.execute(
            """
            UPDATE webhook_deliveries
               SET status          = ?,
                   attempts        = ?,
                   last_attempt_at = ?,
                   next_retry_at   = ?,
                   response_code   = ?,
                   response_body   = ?
             WHERE id = ?
            """,
            (new_status, attempts, now, next_retry_at, status_code, body, delivery_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------

    async def process_retries(self) -> None:
        """Retry all pending deliveries whose next_retry_at has elapsed."""
        assert self._db is not None, "call connect() first"

        now = time.time()
        cursor = await self._db.execute(
            """
            SELECT d.*, w.url, w.secret, w.event_types, w.agent_id, w.active
              FROM webhook_deliveries d
              JOIN webhooks w ON w.id = d.webhook_id
             WHERE d.status = 'pending'
               AND d.next_retry_at IS NOT NULL
               AND d.next_retry_at <= ?
            """,
            (now,),
        )
        rows = await cursor.fetchall()

        for row in rows:
            webhook = {
                "id": row["webhook_id"],
                "agent_id": row["agent_id"],
                "url": row["url"],
                "event_types": json.loads(row["event_types"]),
                "secret": row["secret"],
                "active": row["active"],
            }
            event: dict[str, Any] = json.loads(row["payload"])
            delivery_id: int = row["id"]
            await self._send(webhook, delivery_id, event)

    # ------------------------------------------------------------------
    # Delivery history
    # ------------------------------------------------------------------

    async def get_delivery_history(
        self, webhook_id: str, limit: int = 50
    ) -> list[dict]:
        """Return delivery history for a webhook, most recent first."""
        assert self._db is not None, "call connect() first"

        cursor = await self._db.execute(
            """
            SELECT id, webhook_id, event_type, payload, status, attempts,
                   last_attempt_at, next_retry_at, response_code, response_body,
                   created_at
              FROM webhook_deliveries
             WHERE webhook_id = ?
             ORDER BY created_at DESC
             LIMIT ?
            """,
            (webhook_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _insert_delivery(
        self,
        webhook_id: str,
        event_type: str,
        payload_json: str,
        now: float,
    ) -> int:
        """Insert a new delivery record and return its id."""
        assert self._db is not None
        cursor = await self._db.execute(
            """
            INSERT INTO webhook_deliveries
                (webhook_id, event_type, payload, status, attempts, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?)
            """,
            (webhook_id, event_type, payload_json, now),
        )
        await self._db.commit()
        assert cursor.lastrowid is not None
        return cursor.lastrowid

    @staticmethod
    def _row_to_webhook(row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row into a webhook dict."""
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "url": row["url"],
            "event_types": json.loads(row["event_types"]),
            "secret": row["secret"],
            "created_at": row["created_at"],
            "active": row["active"],
        }
