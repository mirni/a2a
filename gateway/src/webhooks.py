"""Webhook management with SQLite-backed storage and async delivery."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

import aiosqlite
import httpx

logger = logging.getLogger("a2a.webhooks")

_SCHEMA_WEBHOOKS = """
CREATE TABLE IF NOT EXISTS webhooks (
    id               TEXT PRIMARY KEY,
    agent_id         TEXT    NOT NULL,
    url              TEXT    NOT NULL,
    event_types      TEXT    NOT NULL,  -- JSON array
    secret           TEXT    NOT NULL,
    created_at       REAL    NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1,
    filter_agent_ids TEXT             -- JSON array or NULL (deliver all)
);
"""

# Fields in an event payload that may contain an agent identifier.
_AGENT_ID_FIELDS = ("agent_id", "payer", "payee", "sender", "recipient")

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

    def __init__(self, dsn: str, max_concurrent_sends: int = 10) -> None:
        self._dsn = dsn
        self._db: aiosqlite.Connection | None = None
        self._send_semaphore = asyncio.Semaphore(max_concurrent_sends)

    def _require_db(self) -> aiosqlite.Connection:
        """Return the database connection, raising RuntimeError if not connected."""
        if self._db is None:
            raise RuntimeError("WebhookManager not connected — call connect() first")
        return self._db

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

    @staticmethod
    def _validate_webhook_url(url: str) -> None:
        """Validate webhook URL: must be HTTPS, no private/loopback IPs."""
        import ipaddress
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError(f"Webhook URL must use HTTPS scheme, got '{parsed.scheme}'")

        hostname = parsed.hostname
        if not hostname:
            raise ValueError("Webhook URL has no hostname")

        # Check if hostname is an IP address
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                raise ValueError(f"Webhook URL must not target private/loopback/link-local IP: {hostname}")
        except ValueError as exc:
            if "private" in str(exc) or "loopback" in str(exc) or "link-local" in str(exc) or "HTTPS" in str(exc):
                raise
            # hostname is not an IP — try resolving
            try:
                resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
                for family, _type, _proto, _canonname, sockaddr in resolved:
                    ip_str = sockaddr[0]
                    addr = ipaddress.ip_address(ip_str)
                    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
                        raise ValueError(
                            f"Webhook URL hostname '{hostname}' resolves to private/reserved IP: {ip_str}"
                        )
            except (socket.gaierror, OSError):
                pass  # DNS resolution failure is OK at registration time

    async def register(
        self,
        agent_id: str,
        url: str,
        event_types: list[str],
        secret: str,
        filter_agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register a new webhook and return its representation."""
        self._require_db()
        self._validate_webhook_url(url)

        webhook_id = f"whk-{secrets.token_hex(12)}"
        created_at = time.time()
        event_types_json = json.dumps(event_types)
        filter_json = json.dumps(filter_agent_ids) if filter_agent_ids else None

        await self._db.execute(
            """
            INSERT INTO webhooks
                (id, agent_id, url, event_types, secret, created_at, active, filter_agent_ids)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (webhook_id, agent_id, url, event_types_json, secret, created_at, filter_json),
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
            "filter_agent_ids": filter_agent_ids,
        }

    async def list_webhooks(self, agent_id: str) -> list[dict[str, Any]]:
        """Return all webhooks belonging to *agent_id*."""
        self._require_db()

        cursor = await self._db.execute(
            "SELECT * FROM webhooks WHERE agent_id = ? AND active = 1",
            (agent_id,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_webhook(row) for row in rows]

    async def delete_webhook(self, webhook_id: str) -> bool:
        """Soft-delete a webhook. Returns True if it existed and was active."""
        self._require_db()

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
        """Queue delivery records for every active webhook matching *event_type*.

        When a webhook has ``filter_agent_ids`` set, the event is only delivered
        if one of the common agent-identifying fields (``agent_id``, ``payer``,
        ``payee``, ``sender``, ``recipient``) contains a value present in the
        filter list.  Events with **no** recognised agent field are always
        delivered (no false negatives).
        """
        self._require_db()

        event_type = event.get("type", "")
        now = time.time()
        payload_json = json.dumps(event)

        cursor = await self._db.execute(
            "SELECT * FROM webhooks WHERE active = 1",
        )
        webhooks = await cursor.fetchall()

        # Extract agent ids from event payload once.
        event_agent_ids = self._extract_agent_ids(event)

        for row in webhooks:
            registered_types: list[str] = json.loads(row["event_types"])
            if event_type not in registered_types:
                continue

            webhook = self._row_to_webhook(row)

            # Apply agent_id filter when configured.
            if not self._matches_agent_filter(webhook, event_agent_ids):
                continue

            delivery_id = await self._insert_delivery(
                webhook_id=webhook["id"],
                event_type=event_type,
                payload_json=payload_json,
                now=now,
            )
            asyncio.create_task(
                self._guarded_send(webhook, delivery_id, event),
                name=f"webhook-send-{webhook['id']}-{delivery_id}",
            )

    async def _send(
        self,
        webhook: dict[str, Any],
        delivery_id: int,
        event: dict[str, Any],
    ) -> None:
        """POST the event payload to the webhook URL with HMAC-SHA3 signature."""
        self._require_db()

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

        try:
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
        except Exception:
            await self._db.rollback()
            raise

    async def _guarded_send(
        self,
        webhook: dict[str, Any],
        delivery_id: int,
        event: dict[str, Any],
    ) -> None:
        """Wrap _send with semaphore and error handling for fire-and-forget delivery."""
        try:
            async with self._send_semaphore:
                await self._send(webhook, delivery_id, event)
        except Exception:
            logger.exception(
                "Background webhook send failed for webhook %s delivery %s",
                webhook.get("id"),
                delivery_id,
            )

    # ------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------

    async def process_retries(self) -> None:
        """Retry all pending deliveries whose next_retry_at has elapsed."""
        self._require_db()

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

    async def get_delivery_history(self, webhook_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return delivery history for a webhook, most recent first."""
        self._require_db()

        cursor = await self._db.execute(
            """
            SELECT id, webhook_id, event_type, payload, status, attempts,
                   last_attempt_at, next_retry_at, response_code, response_body,
                   created_at
              FROM webhook_deliveries
             WHERE webhook_id = ?
             ORDER BY created_at DESC
             LIMIT ? OFFSET ?
            """,
            (webhook_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    async def get_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        """Look up a single webhook by id. Returns None if not found or inactive."""
        self._require_db()
        cursor = await self._db.execute(
            "SELECT * FROM webhooks WHERE id = ? AND active = 1",
            (webhook_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_webhook(row)

    async def send_test_ping(self, webhook_id: str) -> dict[str, Any]:
        """Send a test.ping event to a registered webhook and return delivery result."""
        import json as _json
        import time as _time

        self._require_db()

        webhook = await self.get_webhook(webhook_id)
        if webhook is None:
            raise LookupError(f"Webhook not found: {webhook_id}")

        now = _time.time()
        event = {
            "type": "test.ping",
            "webhook_id": webhook_id,
            "timestamp": now,
            "message": "Test ping from A2A gateway",
        }
        payload_json = _json.dumps(event)

        delivery_id = await self._insert_delivery(
            webhook_id=webhook_id,
            event_type="test.ping",
            payload_json=payload_json,
            now=now,
        )

        await self._send(webhook, delivery_id, event)

        cursor = await self._db.execute(
            "SELECT id, status, response_code FROM webhook_deliveries WHERE id = ?",
            (delivery_id,),
        )
        result_row = await cursor.fetchone()

        return {
            "delivery_id": result_row["id"],
            "status": result_row["status"],
            "response_code": result_row["response_code"],
        }

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
        self._require_db()
        cursor = await self._db.execute(
            """
            INSERT INTO webhook_deliveries
                (webhook_id, event_type, payload, status, attempts, created_at)
            VALUES (?, ?, ?, 'pending', 0, ?)
            """,
            (webhook_id, event_type, payload_json, now),
        )
        await self._db.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("Failed to insert delivery record")
        return cursor.lastrowid

    @staticmethod
    def _extract_agent_ids(event: dict[str, Any]) -> set[str]:
        """Return the set of agent identifiers found in the event payload."""
        ids: set[str] = set()
        for field in _AGENT_ID_FIELDS:
            value = event.get(field)
            if isinstance(value, str) and value:
                ids.add(value)
        return ids

    @staticmethod
    def _matches_agent_filter(
        webhook: dict[str, Any],
        event_agent_ids: set[str],
    ) -> bool:
        """Return True if the event should be delivered to *webhook*.

        * No filter configured (``None`` / empty) -> always deliver.
        * Filter configured but event has no agent fields -> deliver (no false negatives).
        * Filter configured and event has agent fields -> deliver only if intersection.
        """
        filter_ids: list[str] | None = webhook.get("filter_agent_ids")
        if not filter_ids:
            return True
        if not event_agent_ids:
            return True
        return bool(event_agent_ids & set(filter_ids))

    @staticmethod
    def _row_to_webhook(row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row into a webhook dict."""
        raw_filter = row["filter_agent_ids"]
        filter_agent_ids = json.loads(raw_filter) if raw_filter else None
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "url": row["url"],
            "event_types": json.loads(row["event_types"]),
            "secret": row["secret"],
            "created_at": row["created_at"],
            "active": row["active"],
            "filter_agent_ids": filter_agent_ids,
        }
