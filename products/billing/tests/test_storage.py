"""Tests for the SQLite storage layer."""

from __future__ import annotations

import time

import pytest
from src.storage import StorageBackend


class TestStorageConnection:
    async def test_connect_creates_schema(self, storage: StorageBackend):
        # Verify tables exist by querying sqlite_master
        cursor = await storage.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = await cursor.fetchall()
        table_names = sorted(r["name"] for r in rows)
        assert "wallets" in table_names
        assert "usage_records" in table_names
        assert "transactions" in table_names
        assert "rate_policies" in table_names
        assert "billing_events" in table_names

    async def test_connect_is_idempotent(self, storage: StorageBackend):
        # Calling connect schema again should not fail
        await storage.db.executescript("CREATE TABLE IF NOT EXISTS wallets (agent_id TEXT PRIMARY KEY)")


class TestWalletStorage:
    async def test_create_and_get_wallet(self, storage: StorageBackend):
        wallet = await storage.create_wallet("agent-1", 100.0)
        assert wallet["agent_id"] == "agent-1"
        assert wallet["balance"] == 100.0

        fetched = await storage.get_wallet("agent-1")
        assert fetched is not None
        assert fetched["balance"] == 100.0

    async def test_get_wallet_returns_none_for_missing(self, storage: StorageBackend):
        result = await storage.get_wallet("nonexistent")
        assert result is None

    async def test_update_balance(self, storage: StorageBackend):
        await storage.create_wallet("agent-2", 50.0)
        await storage.update_balance("agent-2", 75.0)
        wallet = await storage.get_wallet("agent-2")
        assert wallet is not None
        assert wallet["balance"] == 75.0


class TestTransactionStorage:
    async def test_record_and_get_transactions(self, storage: StorageBackend):
        tx_id = await storage.record_transaction("agent-1", 100.0, "deposit", "test deposit")
        assert tx_id is not None
        assert tx_id > 0

        txs = await storage.get_transactions("agent-1")
        assert len(txs) == 1
        assert txs[0]["amount"] == 100.0
        assert txs[0]["tx_type"] == "deposit"

    async def test_transactions_ordered_by_time_desc(self, storage: StorageBackend):
        await storage.record_transaction("agent-1", 10.0, "deposit", "first")
        await storage.record_transaction("agent-1", 20.0, "deposit", "second")
        txs = await storage.get_transactions("agent-1")
        assert txs[0]["description"] == "second"
        assert txs[1]["description"] == "first"

    async def test_transactions_limit_and_offset(self, storage: StorageBackend):
        for i in range(5):
            await storage.record_transaction("agent-1", float(i), "deposit", f"tx-{i}")
        txs = await storage.get_transactions("agent-1", limit=2, offset=1)
        assert len(txs) == 2


class TestUsageStorage:
    async def test_record_and_get_usage(self, storage: StorageBackend):
        uid = await storage.record_usage("agent-1", "my_func", 2.5, tokens=100)
        assert uid > 0

        records = await storage.get_usage("agent-1")
        assert len(records) == 1
        assert records[0]["function"] == "my_func"
        assert records[0]["cost"] == 2.5
        assert records[0]["tokens"] == 100

    async def test_usage_with_metadata(self, storage: StorageBackend):
        await storage.record_usage("agent-1", "func", 1.0, metadata={"key": "value"})
        records = await storage.get_usage("agent-1")
        assert records[0]["metadata"] == {"key": "value"}

    async def test_usage_time_filtering(self, storage: StorageBackend):
        now = time.time()
        await storage.record_usage("agent-1", "func", 1.0)
        records = await storage.get_usage("agent-1", since=now - 10)
        assert len(records) == 1
        records = await storage.get_usage("agent-1", since=now + 100)
        assert len(records) == 0

    async def test_usage_summary(self, storage: StorageBackend):
        await storage.record_usage("agent-1", "f1", 2.0, tokens=10)
        await storage.record_usage("agent-1", "f2", 3.0, tokens=20)
        summary = await storage.get_usage_summary("agent-1")
        assert summary["total_calls"] == 2
        assert summary["total_cost"] == 5.0
        assert summary["total_tokens"] == 30

    async def test_usage_summary_empty(self, storage: StorageBackend):
        summary = await storage.get_usage_summary("nobody")
        assert summary["total_calls"] == 0
        assert summary["total_cost"] == 0.0


class TestRatePolicyStorage:
    async def test_set_and_get_policy(self, storage: StorageBackend):
        await storage.set_rate_policy("agent-1", max_calls_per_min=10, max_spend_per_day=100.0)
        policy = await storage.get_rate_policy("agent-1")
        assert policy is not None
        assert policy["max_calls_per_min"] == 10
        assert policy["max_spend_per_day"] == 100.0

    async def test_get_policy_returns_none_for_missing(self, storage: StorageBackend):
        assert await storage.get_rate_policy("none") is None

    async def test_upsert_policy(self, storage: StorageBackend):
        await storage.set_rate_policy("agent-1", max_calls_per_min=5)
        await storage.set_rate_policy("agent-1", max_calls_per_min=20, max_spend_per_day=50.0)
        policy = await storage.get_rate_policy("agent-1")
        assert policy["max_calls_per_min"] == 20
        assert policy["max_spend_per_day"] == 50.0

    async def test_delete_policy(self, storage: StorageBackend):
        await storage.set_rate_policy("agent-1", max_calls_per_min=10)
        await storage.delete_rate_policy("agent-1")
        assert await storage.get_rate_policy("agent-1") is None


class TestCountAndSumHelpers:
    async def test_count_calls_since(self, storage: StorageBackend):
        now = time.time()
        await storage.record_usage("agent-1", "f", 1.0)
        await storage.record_usage("agent-1", "f", 1.0)
        count = await storage.count_calls_since("agent-1", now - 10)
        assert count == 2
        count = await storage.count_calls_since("agent-1", now + 100)
        assert count == 0

    async def test_sum_cost_since(self, storage: StorageBackend):
        now = time.time()
        await storage.record_usage("agent-1", "f", 2.5)
        await storage.record_usage("agent-1", "f", 3.5)
        total = await storage.sum_cost_since("agent-1", now - 10)
        assert total == 6.0


class TestBillingEventStorage:
    async def test_emit_and_get_pending(self, storage: StorageBackend):
        eid = await storage.emit_event("test.event", "agent-1", {"key": "val"})
        assert eid > 0
        pending = await storage.get_pending_events()
        assert len(pending) == 1
        assert pending[0]["event_type"] == "test.event"
        assert pending[0]["payload"] == {"key": "val"}

    async def test_mark_delivered(self, storage: StorageBackend):
        eid = await storage.emit_event("test.event", "agent-1", {"x": 1})
        await storage.mark_event_delivered(eid)
        pending = await storage.get_pending_events()
        assert len(pending) == 0

    async def test_get_events_by_agent(self, storage: StorageBackend):
        await storage.emit_event("e1", "agent-1", {"a": 1})
        await storage.emit_event("e2", "agent-2", {"b": 2})
        events = await storage.get_events("agent-1")
        assert len(events) == 1
        assert events[0]["event_type"] == "e1"


class TestAtomicCreditRetry:
    """v1.2.9 audit RACE1.1: atomic_credit retries on SQLITE_BUSY."""

    async def test_atomic_credit_retries_on_locked(self, storage: StorageBackend):
        """Simulate 'database is locked' on first attempt, succeed on retry."""
        import sqlite3
        from unittest.mock import patch

        await storage.create_wallet("retry-agent", 100.0)

        call_count = 0
        original_execute = storage.db.execute

        async def _flaky_execute(sql, *args, **kwargs):
            nonlocal call_count
            if "BEGIN IMMEDIATE" in str(sql):
                call_count += 1
                if call_count == 1:
                    raise sqlite3.OperationalError("database is locked")
            return await original_execute(sql, *args, **kwargs)

        with patch.object(storage.db, "execute", side_effect=_flaky_execute):
            success, balance = await storage.atomic_credit("retry-agent", 50.0)

        assert success is True
        assert balance == 150.0
        assert call_count >= 2  # at least 1 retry

    async def test_atomic_credit_non_locked_error_not_retried(self, storage: StorageBackend):
        """Non-'database is locked' errors should propagate immediately."""
        import sqlite3
        from unittest.mock import patch

        await storage.create_wallet("err-agent", 100.0)

        async def _error_execute(sql, *args, **kwargs):
            if "BEGIN IMMEDIATE" in str(sql):
                raise sqlite3.OperationalError("disk I/O error")
            return await storage.db.execute(sql, *args, **kwargs)

        with patch.object(storage.db, "execute", side_effect=_error_execute):
            with pytest.raises(sqlite3.OperationalError, match="disk I/O"):
                await storage.atomic_credit("err-agent", 10.0)

    async def test_atomic_credit_succeeds_without_retry(self, storage: StorageBackend):
        """Normal atomic_credit succeeds without needing retry."""
        await storage.create_wallet("normal-agent", 200.0)
        success, balance = await storage.atomic_credit("normal-agent", 30.0)
        assert success is True
        assert balance == 230.0


class TestStorageNotConnected:
    async def test_db_raises_when_not_connected(self):
        s = StorageBackend(dsn="sqlite:///test.db")
        with pytest.raises(RuntimeError, match="not connected"):
            _ = s.db
