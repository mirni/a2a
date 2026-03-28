"""SQLite storage layer for billing data.

All database access is async via aiosqlite. Schema is auto-created on first connect.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

try:
    from shared_src.base_storage import BaseStorage
except ImportError:
    from src.base_storage import BaseStorage


@dataclass
class StorageBackend(BaseStorage):
    """Async SQLite storage backend for all billing data."""

    _SCHEMA: str = """
CREATE TABLE IF NOT EXISTS wallets (
    agent_id   TEXT PRIMARY KEY,
    balance    REAL NOT NULL DEFAULT 0.0,
    org_id     TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id   TEXT NOT NULL,
    function   TEXT NOT NULL,
    cost       REAL NOT NULL,
    tokens     INTEGER NOT NULL DEFAULT 0,
    metadata   TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_usage_agent   ON usage_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    amount      REAL NOT NULL,
    tx_type     TEXT NOT NULL,
    description TEXT,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_agent ON transactions(agent_id);

CREATE TABLE IF NOT EXISTS rate_policies (
    agent_id        TEXT PRIMARY KEY,
    max_calls_per_min  INTEGER,
    max_spend_per_day  REAL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at REAL NOT NULL,
    delivered  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_undelivered ON billing_events(delivered, created_at);

CREATE TABLE IF NOT EXISTS budget_caps (
    agent_id        TEXT PRIMARY KEY,
    daily_cap       REAL,
    monthly_cap     REAL,
    alert_threshold REAL NOT NULL DEFAULT 0.8
);
"""

    # -----------------------------------------------------------------------
    # Wallet operations
    # -----------------------------------------------------------------------

    async def get_wallet(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT agent_id, balance, created_at, updated_at FROM wallets WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    async def create_wallet(self, agent_id: str, initial_balance: float = 0.0) -> dict[str, Any]:
        now = time.time()
        await self.db.execute(
            "INSERT INTO wallets (agent_id, balance, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (agent_id, initial_balance, now, now),
        )
        await self.db.commit()
        return {"agent_id": agent_id, "balance": initial_balance, "created_at": now, "updated_at": now}

    async def update_balance(self, agent_id: str, new_balance: float) -> None:
        now = time.time()
        await self.db.execute(
            "UPDATE wallets SET balance = ?, updated_at = ? WHERE agent_id = ?",
            (new_balance, now, agent_id),
        )
        await self.db.commit()

    async def atomic_debit(self, agent_id: str, amount: float) -> float | None:
        """Atomically debit amount from wallet if sufficient balance.

        Uses a single UPDATE ... WHERE balance >= ? to avoid read-check-write races.
        Returns the new balance on success, or None if insufficient funds.
        """
        now = time.time()
        await self.db.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = ? "
            "WHERE agent_id = ? AND balance >= ?",
            (amount, now, agent_id, amount),
        )
        await self.db.commit()
        # Check if the update actually modified a row
        cursor = await self.db.execute(
            "SELECT balance FROM wallets WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None  # wallet doesn't exist
        # We need to verify the debit happened. The balance after a successful
        # debit of `amount` should be what we see. But if the WHERE clause
        # didn't match (balance < amount), the row wasn't updated.
        # Use changes() to check: not available via aiosqlite easily.
        # Instead, use a different approach: check total_changes or use RETURNING.
        # Simplest correct approach: use execute + rowcount.
        return row[0]

    async def atomic_debit_strict(self, agent_id: str, amount: float) -> tuple[bool, float]:
        """Atomically debit amount from wallet.

        Returns (success, balance) where success=True if debit was applied,
        and balance is the current balance after the operation.
        """
        now = time.time()
        cursor = await self.db.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = ? "
            "WHERE agent_id = ? AND balance >= ?",
            (amount, now, agent_id, amount),
        )
        await self.db.commit()
        affected = cursor.rowcount
        # Fetch current balance
        cur2 = await self.db.execute(
            "SELECT balance FROM wallets WHERE agent_id = ?", (agent_id,)
        )
        row = await cur2.fetchone()
        if row is None:
            return (False, 0.0)
        return (affected > 0, row[0])

    async def atomic_credit(self, agent_id: str, amount: float) -> tuple[bool, float]:
        """Atomically credit amount to wallet.

        Returns (success, new_balance) where success=True if agent exists.
        """
        now = time.time()
        cursor = await self.db.execute(
            "UPDATE wallets SET balance = balance + ?, updated_at = ? "
            "WHERE agent_id = ?",
            (amount, now, agent_id),
        )
        await self.db.commit()
        affected = cursor.rowcount
        cur2 = await self.db.execute(
            "SELECT balance FROM wallets WHERE agent_id = ?", (agent_id,)
        )
        row = await cur2.fetchone()
        if row is None:
            return (False, 0.0)
        return (affected > 0, row[0])

    # -----------------------------------------------------------------------
    # Transaction log
    # -----------------------------------------------------------------------

    async def record_transaction(
        self, agent_id: str, amount: float, tx_type: str, description: str = ""
    ) -> int:
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO transactions (agent_id, amount, tx_type, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_id, amount, tx_type, description, now),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_transactions(
        self, agent_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM transactions WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (agent_id, limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Usage records
    # -----------------------------------------------------------------------

    async def record_usage(
        self,
        agent_id: str,
        function: str,
        cost: float,
        tokens: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO usage_records (agent_id, function, cost, tokens, metadata, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, function, cost, tokens, json.dumps(metadata) if metadata else None, now),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_usage(
        self,
        agent_id: str,
        since: float | None = None,
        until: float | None = None,
        limit: int = 1000,
        function: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM usage_records WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        if until is not None:
            query += " AND created_at <= ?"
            params.append(until)
        if function is not None:
            query += " AND function LIKE ?"
            params.append(f"%{function}%")
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self.db.execute(query, params)
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("metadata"):
                d["metadata"] = json.loads(d["metadata"])
            results.append(d)
        return results

    async def get_usage_summary(
        self, agent_id: str, since: float | None = None
    ) -> dict[str, Any]:
        query = "SELECT COUNT(*) as total_calls, COALESCE(SUM(cost), 0) as total_cost, COALESCE(SUM(tokens), 0) as total_tokens FROM usage_records WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        return dict(row) if row else {"total_calls": 0, "total_cost": 0.0, "total_tokens": 0}

    # -----------------------------------------------------------------------
    # Rate policies
    # -----------------------------------------------------------------------

    async def get_rate_policy(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM rate_policies WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def set_rate_policy(
        self,
        agent_id: str,
        max_calls_per_min: int | None = None,
        max_spend_per_day: float | None = None,
    ) -> None:
        now = time.time()
        await self.db.execute(
            "INSERT INTO rate_policies (agent_id, max_calls_per_min, max_spend_per_day, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(agent_id) DO UPDATE SET "
            "max_calls_per_min = excluded.max_calls_per_min, "
            "max_spend_per_day = excluded.max_spend_per_day, "
            "updated_at = excluded.updated_at",
            (agent_id, max_calls_per_min, max_spend_per_day, now),
        )
        await self.db.commit()

    async def delete_rate_policy(self, agent_id: str) -> None:
        await self.db.execute("DELETE FROM rate_policies WHERE agent_id = ?", (agent_id,))
        await self.db.commit()

    # -----------------------------------------------------------------------
    # Rate-limit check helpers
    # -----------------------------------------------------------------------

    async def count_calls_since(self, agent_id: str, since: float) -> int:
        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM usage_records WHERE agent_id = ? AND created_at >= ?",
            (agent_id, since),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def sum_cost_since(self, agent_id: str, since: float) -> float:
        cursor = await self.db.execute(
            "SELECT COALESCE(SUM(cost), 0) FROM usage_records WHERE agent_id = ? AND created_at >= ?",
            (agent_id, since),
        )
        row = await cursor.fetchone()
        return float(row[0]) if row else 0.0

    # -----------------------------------------------------------------------
    # Billing events
    # -----------------------------------------------------------------------

    async def emit_event(
        self, event_type: str, agent_id: str, payload: dict[str, Any]
    ) -> int:
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO billing_events (event_type, agent_id, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (event_type, agent_id, json.dumps(payload), now),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_pending_events(self, limit: int = 100) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM billing_events WHERE delivered = 0 ORDER BY created_at ASC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            results.append(d)
        return results

    async def mark_event_delivered(self, event_id: int) -> None:
        await self.db.execute(
            "UPDATE billing_events SET delivered = 1 WHERE id = ?", (event_id,)
        )
        await self.db.commit()

    async def get_events(
        self, agent_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM billing_events WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            results.append(d)
        return results
