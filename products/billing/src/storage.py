"""SQLite storage layer for billing data.

All database access is async via aiosqlite. Schema is auto-created on first connect.

Monetary values are stored as INTEGER in atomic units (1 credit = 10^8 atomic).
Conversion happens at the storage boundary using the shared money module.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

try:
    from shared_src.base_storage import BaseStorage
    from shared_src.migrate import Migration
    from shared_src.money import SCALE, atomic_to_float, credits_to_atomic
except ImportError:
    from src.base_storage import BaseStorage
    from src.migrate import Migration
    from src.money import SCALE, atomic_to_float, credits_to_atomic


@dataclass
class StorageBackend(BaseStorage):
    """Async SQLite storage backend for all billing data."""

    _SCHEMA: str = """
CREATE TABLE IF NOT EXISTS wallets (
    agent_id   TEXT PRIMARY KEY,
    balance    INTEGER NOT NULL DEFAULT 0,
    org_id     TEXT NOT NULL DEFAULT 'default',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL,
    function        TEXT NOT NULL,
    cost            INTEGER NOT NULL DEFAULT 0,
    tokens          INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT,
    created_at      REAL NOT NULL,
    idempotency_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_usage_agent   ON usage_records(agent_id);
CREATE INDEX IF NOT EXISTS idx_usage_created ON usage_records(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_idempotency ON usage_records(idempotency_key);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL,
    amount      INTEGER NOT NULL DEFAULT 0,
    tx_type     TEXT NOT NULL,
    description TEXT,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tx_agent ON transactions(agent_id);

CREATE TABLE IF NOT EXISTS rate_policies (
    agent_id        TEXT PRIMARY KEY,
    max_calls_per_min  INTEGER,
    max_spend_per_day  INTEGER,
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
    daily_cap       INTEGER,
    monthly_cap     INTEGER,
    alert_threshold REAL NOT NULL DEFAULT 0.8
);

CREATE TABLE IF NOT EXISTS auto_reload_config (
    agent_id       TEXT PRIMARY KEY,
    threshold      INTEGER NOT NULL,
    reload_amount  INTEGER NOT NULL,
    enabled        INTEGER NOT NULL DEFAULT 1
);
"""

    _MIGRATIONS: tuple[Migration, ...] = (
        Migration(
            1,
            "add idempotency_key to usage_records",
            "ALTER TABLE usage_records ADD COLUMN idempotency_key TEXT;\n"
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_idempotency "
            "ON usage_records(idempotency_key);",
        ),
        Migration(
            2,
            "convert monetary columns from REAL to INTEGER (atomic units, SCALE=1e8)",
            # Detect if migration is needed (balance is REAL with fractional part)
            # Use ROUND to avoid float truncation issues (0.1*1e8=9999999.99...)
            "UPDATE wallets SET balance = CAST(ROUND(balance * 100000000) AS INTEGER) "
            "WHERE typeof(balance) = 'real' OR (balance > 0 AND balance < 100000000);\n"
            "UPDATE usage_records SET cost = CAST(ROUND(cost * 100000000) AS INTEGER) "
            "WHERE typeof(cost) = 'real' OR (cost > 0 AND cost < 100000000);\n"
            "UPDATE transactions SET amount = CAST(ROUND(amount * 100000000) AS INTEGER) "
            "WHERE typeof(amount) = 'real' OR (amount != 0 AND amount < 100000000 AND amount > -100000000);\n"
            "UPDATE rate_policies SET max_spend_per_day = CAST(ROUND(max_spend_per_day * 100000000) AS INTEGER) "
            "WHERE max_spend_per_day IS NOT NULL AND (typeof(max_spend_per_day) = 'real' OR (max_spend_per_day > 0 AND max_spend_per_day < 100000000));\n"
            "UPDATE budget_caps SET daily_cap = CAST(ROUND(daily_cap * 100000000) AS INTEGER) "
            "WHERE daily_cap IS NOT NULL AND (typeof(daily_cap) = 'real' OR (daily_cap > 0 AND daily_cap < 100000000));\n"
            "UPDATE budget_caps SET monthly_cap = CAST(ROUND(monthly_cap * 100000000) AS INTEGER) "
            "WHERE monthly_cap IS NOT NULL AND (typeof(monthly_cap) = 'real' OR (monthly_cap > 0 AND monthly_cap < 100000000));",
        ),
        Migration(
            3,
            "add auto_reload_config table",
            "CREATE TABLE IF NOT EXISTS auto_reload_config (\n"
            "    agent_id       TEXT PRIMARY KEY,\n"
            "    threshold      INTEGER NOT NULL,\n"
            "    reload_amount  INTEGER NOT NULL,\n"
            "    enabled        INTEGER NOT NULL DEFAULT 1\n"
            ");",
        ),
    )

    # -----------------------------------------------------------------------
    # Wallet operations
    # -----------------------------------------------------------------------

    def _to_atomic(self, value: float) -> int:
        """Convert a float credit amount to atomic units at the storage boundary."""
        return credits_to_atomic(Decimal(str(value)))

    def _from_atomic(self, atomic: int) -> float:
        """Convert atomic units back to float at the storage boundary."""
        return atomic_to_float(atomic)

    async def get_wallet(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT agent_id, balance, created_at, updated_at FROM wallets WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["balance"] = self._from_atomic(d["balance"])
        return d

    async def create_wallet(self, agent_id: str, initial_balance: float = 0.0) -> dict[str, Any]:
        now = time.time()
        bal_atomic = self._to_atomic(initial_balance)
        await self.db.execute(
            "INSERT INTO wallets (agent_id, balance, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (agent_id, bal_atomic, now, now),
        )
        await self.db.commit()
        return {"agent_id": agent_id, "balance": initial_balance, "created_at": now, "updated_at": now}

    async def update_balance(self, agent_id: str, new_balance: float) -> None:
        now = time.time()
        bal_atomic = self._to_atomic(new_balance)
        await self.db.execute(
            "UPDATE wallets SET balance = ?, updated_at = ? WHERE agent_id = ?",
            (bal_atomic, now, agent_id),
        )
        await self.db.commit()

    async def atomic_debit(self, agent_id: str, amount: float) -> float | None:
        """Atomically debit amount from wallet if sufficient balance.

        Uses a single UPDATE ... WHERE balance >= ? to avoid read-check-write races.
        Returns the new balance on success, or None if insufficient funds.
        """
        now = time.time()
        amt_atomic = self._to_atomic(amount)
        await self.db.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE agent_id = ? AND balance >= ?",
            (amt_atomic, now, agent_id, amt_atomic),
        )
        await self.db.commit()
        cursor = await self.db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._from_atomic(row[0])

    async def atomic_debit_strict(self, agent_id: str, amount: float) -> tuple[bool, float]:
        """Atomically debit amount from wallet.

        Returns (success, balance) where success=True if debit was applied,
        and balance is the current balance after the operation.
        """
        now = time.time()
        amt_atomic = self._to_atomic(amount)
        cursor = await self.db.execute(
            "UPDATE wallets SET balance = balance - ?, updated_at = ? WHERE agent_id = ? AND balance >= ?",
            (amt_atomic, now, agent_id, amt_atomic),
        )
        await self.db.commit()
        affected = cursor.rowcount
        cur2 = await self.db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (agent_id,))
        row = await cur2.fetchone()
        if row is None:
            return (False, 0.0)
        return (affected > 0, self._from_atomic(row[0]))

    async def atomic_credit(self, agent_id: str, amount: float) -> tuple[bool, float]:
        """Atomically credit amount to wallet.

        Returns (success, new_balance) where success=True if agent exists.
        """
        now = time.time()
        amt_atomic = self._to_atomic(amount)
        cursor = await self.db.execute(
            "UPDATE wallets SET balance = balance + ?, updated_at = ? WHERE agent_id = ?",
            (amt_atomic, now, agent_id),
        )
        await self.db.commit()
        affected = cursor.rowcount
        cur2 = await self.db.execute("SELECT balance FROM wallets WHERE agent_id = ?", (agent_id,))
        row = await cur2.fetchone()
        if row is None:
            return (False, 0.0)
        return (affected > 0, self._from_atomic(row[0]))

    # -----------------------------------------------------------------------
    # Transaction log
    # -----------------------------------------------------------------------

    async def record_transaction(self, agent_id: str, amount: float, tx_type: str, description: str = "") -> int:
        now = time.time()
        amt_atomic = int(Decimal(str(amount)) * SCALE)  # allow negative for withdrawals
        cursor = await self.db.execute(
            "INSERT INTO transactions (agent_id, amount, tx_type, description, created_at) VALUES (?, ?, ?, ?, ?)",
            (agent_id, amt_atomic, tx_type, description, now),
        )
        await self.db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_transactions(self, agent_id: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        cursor = await self.db.execute(
            "SELECT * FROM transactions WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (agent_id, limit, offset),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["amount"] = self._from_atomic(d["amount"])
            results.append(d)
        return results

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
        idempotency_key: str | None = None,
    ) -> int:
        now = time.time()
        if idempotency_key is not None:
            cursor = await self.db.execute(
                "SELECT id FROM usage_records WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                return existing[0]
        cost_atomic = self._to_atomic(cost)
        cursor = await self.db.execute(
            "INSERT INTO usage_records (agent_id, function, cost, tokens, metadata, created_at, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (agent_id, function, cost_atomic, tokens, json.dumps(metadata) if metadata else None, now, idempotency_key),
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
            d["cost"] = self._from_atomic(d["cost"])
            if d.get("metadata"):
                d["metadata"] = json.loads(d["metadata"])
            results.append(d)
        return results

    async def get_usage_summary(self, agent_id: str, since: float | None = None) -> dict[str, Any]:
        query = "SELECT COUNT(*) as total_calls, COALESCE(SUM(cost), 0) as total_cost, COALESCE(SUM(tokens), 0) as total_tokens FROM usage_records WHERE agent_id = ?"
        params: list[Any] = [agent_id]
        if since is not None:
            query += " AND created_at >= ?"
            params.append(since)
        cursor = await self.db.execute(query, params)
        row = await cursor.fetchone()
        if row is None:
            return {"total_calls": 0, "total_cost": 0.0, "total_tokens": 0}
        d = dict(row)
        d["total_cost"] = self._from_atomic(d["total_cost"])
        return d

    # -----------------------------------------------------------------------
    # Rate policies
    # -----------------------------------------------------------------------

    async def get_rate_policy(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute("SELECT * FROM rate_policies WHERE agent_id = ?", (agent_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        if d.get("max_spend_per_day") is not None:
            d["max_spend_per_day"] = self._from_atomic(d["max_spend_per_day"])
        return d

    async def set_rate_policy(
        self,
        agent_id: str,
        max_calls_per_min: int | None = None,
        max_spend_per_day: float | None = None,
    ) -> None:
        now = time.time()
        spend_atomic = self._to_atomic(max_spend_per_day) if max_spend_per_day is not None else None
        await self.db.execute(
            "INSERT INTO rate_policies (agent_id, max_calls_per_min, max_spend_per_day, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(agent_id) DO UPDATE SET "
            "max_calls_per_min = excluded.max_calls_per_min, "
            "max_spend_per_day = excluded.max_spend_per_day, "
            "updated_at = excluded.updated_at",
            (agent_id, max_calls_per_min, spend_atomic, now),
        )
        await self.db.commit()

    async def delete_rate_policy(self, agent_id: str) -> None:
        await self.db.execute("DELETE FROM rate_policies WHERE agent_id = ?", (agent_id,))
        await self.db.commit()

    # -----------------------------------------------------------------------
    # Budget caps
    # -----------------------------------------------------------------------

    async def set_budget_cap(
        self,
        agent_id: str,
        daily_cap: float | None = None,
        monthly_cap: float | None = None,
        alert_threshold: float = 0.8,
    ) -> None:
        daily_atomic = self._to_atomic(daily_cap) if daily_cap is not None else None
        monthly_atomic = self._to_atomic(monthly_cap) if monthly_cap is not None else None
        await self.db.execute(
            "INSERT INTO budget_caps (agent_id, daily_cap, monthly_cap, alert_threshold) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(agent_id) DO UPDATE SET "
            "daily_cap = excluded.daily_cap, monthly_cap = excluded.monthly_cap, "
            "alert_threshold = excluded.alert_threshold",
            (agent_id, daily_atomic, monthly_atomic, alert_threshold),
        )
        await self.db.commit()

    async def get_budget_cap(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM budget_caps WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["daily_cap"] = self._from_atomic(d["daily_cap"]) if d["daily_cap"] is not None else None
        d["monthly_cap"] = self._from_atomic(d["monthly_cap"]) if d["monthly_cap"] is not None else None
        return d

    async def delete_budget_cap(self, agent_id: str) -> None:
        await self.db.execute("DELETE FROM budget_caps WHERE agent_id = ?", (agent_id,))
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
        return self._from_atomic(row[0]) if row else 0.0

    # -----------------------------------------------------------------------
    # Billing events
    # -----------------------------------------------------------------------

    async def emit_event(self, event_type: str, agent_id: str, payload: dict[str, Any]) -> int:
        now = time.time()
        cursor = await self.db.execute(
            "INSERT INTO billing_events (event_type, agent_id, payload, created_at) VALUES (?, ?, ?, ?)",
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
        await self.db.execute("UPDATE billing_events SET delivered = 1 WHERE id = ?", (event_id,))
        await self.db.commit()

    async def get_events(self, agent_id: str, limit: int = 100) -> list[dict[str, Any]]:
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

    # -----------------------------------------------------------------------
    # Auto-reload config
    # -----------------------------------------------------------------------

    async def set_auto_reload(
        self, agent_id: str, threshold: float, reload_amount: float, enabled: bool = True
    ) -> None:
        await self.db.execute(
            """INSERT INTO auto_reload_config (agent_id, threshold, reload_amount, enabled)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 threshold = excluded.threshold,
                 reload_amount = excluded.reload_amount,
                 enabled = excluded.enabled""",
            (agent_id, self._to_atomic(threshold), self._to_atomic(reload_amount), int(enabled)),
        )
        await self.db.commit()

    async def get_auto_reload(self, agent_id: str) -> dict[str, Any] | None:
        cursor = await self.db.execute(
            "SELECT * FROM auto_reload_config WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "agent_id": row["agent_id"],
            "threshold": self._from_atomic(row["threshold"]),
            "reload_amount": self._from_atomic(row["reload_amount"]),
            "enabled": bool(row["enabled"]),
        }
