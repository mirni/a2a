"""SQLite storage layer for the payment system.

Follows the same pattern as billing StorageBackend: async connect(), close(),
schema auto-created on connect. All access via aiosqlite.

Monetary values are stored as INTEGER in atomic units (1 credit = 10^8 atomic).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import aiosqlite

try:
    from shared_src.money import SCALE, atomic_to_float, credits_to_atomic
except ImportError:
    from src.money import SCALE, atomic_to_float, credits_to_atomic

# Register Decimal adapter: convert to atomic integer units for SQLite binding
sqlite3.register_adapter(Decimal, lambda d: int(d * SCALE))

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS payment_intents (
    id              TEXT PRIMARY KEY,
    payer           TEXT NOT NULL,
    payee           TEXT NOT NULL,
    amount          INTEGER NOT NULL DEFAULT 0,
    description     TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    settlement_id   TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_intent_idempotency
    ON payment_intents(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_intent_payer ON payment_intents(payer);
CREATE INDEX IF NOT EXISTS idx_intent_payee ON payment_intents(payee);
CREATE INDEX IF NOT EXISTS idx_intent_status ON payment_intents(status);

CREATE TABLE IF NOT EXISTS escrows (
    id            TEXT PRIMARY KEY,
    payer         TEXT NOT NULL,
    payee         TEXT NOT NULL,
    amount        INTEGER NOT NULL DEFAULT 0,
    description   TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'held',
    settlement_id TEXT,
    timeout_at    REAL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    metadata      TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_escrow_payer ON escrows(payer);
CREATE INDEX IF NOT EXISTS idx_escrow_payee ON escrows(payee);
CREATE INDEX IF NOT EXISTS idx_escrow_status ON escrows(status);
CREATE INDEX IF NOT EXISTS idx_escrow_timeout ON escrows(timeout_at) WHERE timeout_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS subscriptions (
    id              TEXT PRIMARY KEY,
    payer           TEXT NOT NULL,
    payee           TEXT NOT NULL,
    amount          INTEGER NOT NULL DEFAULT 0,
    interval        TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    cancelled_by    TEXT,
    next_charge_at  REAL NOT NULL,
    last_charged_at REAL,
    charge_count    INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sub_payer ON subscriptions(payer);
CREATE INDEX IF NOT EXISTS idx_sub_payee ON subscriptions(payee);
CREATE INDEX IF NOT EXISTS idx_sub_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_sub_next_charge ON subscriptions(next_charge_at);

CREATE TABLE IF NOT EXISTS settlements (
    id          TEXT PRIMARY KEY,
    payer       TEXT NOT NULL,
    payee       TEXT NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0,
    source_type TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_settlement_payer ON settlements(payer);
CREATE INDEX IF NOT EXISTS idx_settlement_payee ON settlements(payee);
CREATE INDEX IF NOT EXISTS idx_settlement_source ON settlements(source_type, source_id);
"""


@dataclass
class PaymentStorage:
    """Async SQLite storage backend for payment data."""

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

    def _ensure_connected(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("PaymentStorage not connected. Call connect() first.")
        return self._db

    @property
    def db(self) -> aiosqlite.Connection:
        return self._ensure_connected()

    @staticmethod
    def _convert_amount(d: dict[str, Any]) -> dict[str, Any]:
        """Convert integer 'amount' field back to float at the read boundary."""
        if "amount" in d:
            d["amount"] = atomic_to_float(d["amount"])
        return d

    # -----------------------------------------------------------------------
    # Payment Intents
    # -----------------------------------------------------------------------

    async def insert_intent(self, data: dict[str, Any]) -> None:
        amount = data["amount"]
        # Convert to atomic: Decimal goes via adapter, float needs explicit conversion
        if isinstance(amount, (int, float)) and not isinstance(amount, Decimal):
            amount = credits_to_atomic(Decimal(str(amount)))
        await self.db.execute(
            "INSERT INTO payment_intents "
            "(id, payer, payee, amount, description, idempotency_key, status, "
            "settlement_id, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data["payer"],
                data["payee"],
                amount,
                data.get("description", ""),
                data.get("idempotency_key"),
                data.get("status", "pending"),
                data.get("settlement_id"),
                data["created_at"],
                data["updated_at"],
                json.dumps(data.get("metadata", {})),
            ),
        )
        await self.db.commit()

    async def get_intent(self, intent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM payment_intents WHERE id = ?", (intent_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"])
        return self._convert_amount(d)

    async def get_intent_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM payment_intents WHERE idempotency_key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"])
        return self._convert_amount(d)

    async def update_intent_status(self, intent_id: str, status: str, settlement_id: str | None = None) -> None:
        now = time.time()
        if settlement_id is not None:
            await self.db.execute(
                "UPDATE payment_intents SET status = ?, settlement_id = ?, updated_at = ? WHERE id = ?",
                (status, settlement_id, now, intent_id),
            )
        else:
            await self.db.execute(
                "UPDATE payment_intents SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, intent_id),
            )
        await self.db.commit()

    async def update_intent_amount(self, intent_id: str, amount: float) -> None:
        now = time.time()
        amt_atomic = credits_to_atomic(Decimal(str(amount)))
        await self.db.execute(
            "UPDATE payment_intents SET amount = ?, updated_at = ? WHERE id = ?",
            (amt_atomic, now, intent_id),
        )
        await self.db.commit()

    async def list_intents(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM payment_intents WHERE 1=1"
        params: list[Any] = []
        if agent_id is not None:
            query += " AND (payer = ? OR payee = ?)"
            params.extend([agent_id, agent_id])
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            results.append(self._convert_amount(d))
        return results

    # -----------------------------------------------------------------------
    # Escrows
    # -----------------------------------------------------------------------

    async def insert_escrow(self, data: dict[str, Any]) -> None:
        amount = data["amount"]
        if isinstance(amount, (int, float)) and not isinstance(amount, Decimal):
            amount = credits_to_atomic(Decimal(str(amount)))
        await self.db.execute(
            "INSERT INTO escrows "
            "(id, payer, payee, amount, description, status, settlement_id, "
            "timeout_at, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data["payer"],
                data["payee"],
                amount,
                data.get("description", ""),
                data.get("status", "held"),
                data.get("settlement_id"),
                data.get("timeout_at"),
                data["created_at"],
                data["updated_at"],
                json.dumps(data.get("metadata", {})),
            ),
        )
        await self.db.commit()

    async def get_escrow(self, escrow_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM escrows WHERE id = ?", (escrow_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"])
        return self._convert_amount(d)

    async def update_escrow_status(self, escrow_id: str, status: str, settlement_id: str | None = None) -> None:
        now = time.time()
        if settlement_id is not None:
            await self.db.execute(
                "UPDATE escrows SET status = ?, settlement_id = ?, updated_at = ? WHERE id = ?",
                (status, settlement_id, now, escrow_id),
            )
        else:
            await self.db.execute(
                "UPDATE escrows SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, escrow_id),
            )
        await self.db.commit()

    async def list_escrows(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM escrows WHERE 1=1"
        params: list[Any] = []
        if agent_id is not None:
            query += " AND (payer = ? OR payee = ?)"
            params.extend([agent_id, agent_id])
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            results.append(self._convert_amount(d))
        return results

    async def get_expired_escrows(self, now: float | None = None) -> list[dict[str, Any]]:
        """Return all held escrows that have exceeded their timeout."""
        if now is None:
            now = time.time()
        cursor = await self.db.execute(
            "SELECT * FROM escrows WHERE status = 'held' AND timeout_at IS NOT NULL AND timeout_at <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            results.append(self._convert_amount(d))
        return results

    # -----------------------------------------------------------------------
    # Subscriptions
    # -----------------------------------------------------------------------

    async def insert_subscription(self, data: dict[str, Any]) -> None:
        amount = data["amount"]
        if isinstance(amount, (int, float)) and not isinstance(amount, Decimal):
            amount = credits_to_atomic(Decimal(str(amount)))
        await self.db.execute(
            "INSERT INTO subscriptions "
            "(id, payer, payee, amount, interval, description, status, cancelled_by, "
            "next_charge_at, last_charged_at, charge_count, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data["payer"],
                data["payee"],
                amount,
                data["interval"],
                data.get("description", ""),
                data.get("status", "active"),
                data.get("cancelled_by"),
                data["next_charge_at"],
                data.get("last_charged_at"),
                data.get("charge_count", 0),
                data["created_at"],
                data["updated_at"],
                json.dumps(data.get("metadata", {})),
            ),
        )
        await self.db.commit()

    async def get_subscription(self, sub_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["metadata"] = json.loads(d["metadata"])
        return self._convert_amount(d)

    _SUBSCRIPTION_COLUMNS = frozenset(
        {
            "payer",
            "payee",
            "amount",
            "interval",
            "description",
            "status",
            "cancelled_by",
            "next_charge_at",
            "last_charged_at",
            "charge_count",
            "updated_at",
            "metadata",
        }
    )

    async def update_subscription(self, sub_id: str, updates: dict[str, Any]) -> None:
        now = time.time()
        updates["updated_at"] = now
        # Validate column names against allowlist
        invalid = set(updates.keys()) - self._SUBSCRIPTION_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column(s) in subscription update: {invalid}")
        if "metadata" in updates:
            updates["metadata"] = json.dumps(updates["metadata"])
        # Convert amount to atomic if present
        if "amount" in updates:
            amt = updates["amount"]
            if isinstance(amt, Decimal):
                updates["amount"] = int(amt * SCALE)
            elif isinstance(amt, float):
                updates["amount"] = credits_to_atomic(Decimal(str(amt)))
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [sub_id]
        await self.db.execute(  # nosemgrep: sqlalchemy-execute-raw-query
            f"UPDATE subscriptions SET {set_clause} WHERE id = ?",
            values,
        )
        await self.db.commit()

    async def list_subscriptions(
        self,
        agent_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM subscriptions WHERE 1=1"
        params: list[Any] = []
        if agent_id is not None:
            query += " AND (payer = ? OR payee = ?)"
            params.extend([agent_id, agent_id])
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            results.append(self._convert_amount(d))
        return results

    async def get_due_subscriptions(self, now: float | None = None) -> list[dict[str, Any]]:
        """Return all active subscriptions whose next_charge_at <= now."""
        if now is None:
            now = time.time()
        cursor = await self.db.execute(
            "SELECT * FROM subscriptions WHERE status = 'active' AND next_charge_at <= ?",
            (now,),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d["metadata"])
            results.append(self._convert_amount(d))
        return results

    # -----------------------------------------------------------------------
    # Settlements
    # -----------------------------------------------------------------------

    async def insert_settlement(self, data: dict[str, Any]) -> None:
        amount = data["amount"]
        if isinstance(amount, (int, float)) and not isinstance(amount, Decimal):
            amount = credits_to_atomic(Decimal(str(amount)))
        await self.db.execute(
            "INSERT INTO settlements "
            "(id, payer, payee, amount, source_type, source_id, description, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data["payer"],
                data["payee"],
                amount,
                data["source_type"],
                data["source_id"],
                data.get("description", ""),
                data["created_at"],
            ),
        )
        await self.db.commit()

    async def get_settlement(self, settlement_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM settlements WHERE id = ?", (settlement_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._convert_amount(dict(row))

    async def list_settlements(
        self,
        agent_id: str | None = None,
        source_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM settlements WHERE 1=1"
        params: list[Any] = []
        if agent_id is not None:
            query += " AND (payer = ? OR payee = ?)"
            params.extend([agent_id, agent_id])
        if source_type is not None:
            query += " AND source_type = ?"
            params.append(source_type)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        return [self._convert_amount(dict(r)) for r in rows]

    # -----------------------------------------------------------------------
    # Payment History (unified view)
    # -----------------------------------------------------------------------

    async def get_payment_history(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return a unified payment history for an agent across all tables.

        Combines intents, escrows, subscriptions, and settlements into a single
        chronological list.
        """
        history: list[dict[str, Any]] = []
        # Fetch enough rows from each table to cover offset + limit
        fetch_limit = offset + limit

        # Payment intents
        intents = await self.list_intents(agent_id=agent_id, limit=fetch_limit)
        for intent in intents:
            history.append(
                {
                    "type": "intent",
                    "id": intent["id"],
                    "payer": intent["payer"],
                    "payee": intent["payee"],
                    "amount": intent["amount"],
                    "status": intent["status"],
                    "description": intent["description"],
                    "created_at": intent["created_at"],
                }
            )

        # Escrows
        escrows = await self.list_escrows(agent_id=agent_id, limit=fetch_limit)
        for escrow in escrows:
            history.append(
                {
                    "type": "escrow",
                    "id": escrow["id"],
                    "payer": escrow["payer"],
                    "payee": escrow["payee"],
                    "amount": escrow["amount"],
                    "status": escrow["status"],
                    "description": escrow["description"],
                    "created_at": escrow["created_at"],
                }
            )

        # Subscriptions
        subscriptions = await self.list_subscriptions(agent_id=agent_id, limit=fetch_limit)
        for sub in subscriptions:
            history.append(
                {
                    "type": "subscription",
                    "id": sub["id"],
                    "payer": sub["payer"],
                    "payee": sub["payee"],
                    "amount": sub["amount"],
                    "status": sub["status"],
                    "description": sub["description"],
                    "created_at": sub["created_at"],
                }
            )

        # Settlements
        settlements = await self.list_settlements(agent_id=agent_id, limit=fetch_limit)
        for settlement in settlements:
            history.append(
                {
                    "type": "settlement",
                    "id": settlement["id"],
                    "payer": settlement["payer"],
                    "payee": settlement["payee"],
                    "amount": settlement["amount"],
                    "status": "completed",
                    "description": settlement["description"],
                    "created_at": settlement["created_at"],
                }
            )

        # Sort by created_at descending
        history.sort(key=lambda x: x["created_at"], reverse=True)
        return history[offset : offset + limit]
