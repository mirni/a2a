"""Verify that monetary values are stored as INTEGER in the database (CRIT-2)."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


class TestIntegerStorage:
    async def test_wallet_balance_stored_as_integer(self, storage):
        """Balance should be stored as INTEGER in the DB, not REAL."""
        await storage.create_wallet("int-test", initial_balance=10.5)
        cursor = await storage.db.execute(
            "SELECT balance, typeof(balance) FROM wallets WHERE agent_id = 'int-test'"
        )
        row = await cursor.fetchone()
        assert row[1] == "integer", f"Expected integer, got {row[1]} (value={row[0]})"
        assert row[0] == 1_050_000_000  # 10.5 * 10^8

    async def test_wallet_balance_api_returns_float(self, storage):
        """get_wallet should return balance as a float."""
        await storage.create_wallet("float-test", initial_balance=10.5)
        wallet = await storage.get_wallet("float-test")
        assert wallet["balance"] == 10.5

    async def test_usage_cost_stored_as_integer(self, storage):
        """Usage cost should be stored as INTEGER."""
        await storage.create_wallet("cost-test")
        await storage.record_usage("cost-test", "some_tool", cost=0.01)
        cursor = await storage.db.execute(
            "SELECT cost, typeof(cost) FROM usage_records WHERE agent_id = 'cost-test'"
        )
        row = await cursor.fetchone()
        assert row[1] == "integer", f"Expected integer, got {row[1]} (value={row[0]})"
        assert row[0] == 1_000_000  # 0.01 * 10^8

    async def test_transaction_amount_stored_as_integer(self, storage):
        """Transaction amounts should be stored as INTEGER."""
        await storage.record_transaction("tx-test", 5.25, "deposit", "test")
        cursor = await storage.db.execute(
            "SELECT amount, typeof(amount) FROM transactions WHERE agent_id = 'tx-test'"
        )
        row = await cursor.fetchone()
        assert row[1] == "integer", f"Expected integer, got {row[1]} (value={row[0]})"
        assert row[0] == 525_000_000  # 5.25 * 10^8

    async def test_precision_no_float_loss(self, storage):
        """9.99 should round-trip without IEEE 754 precision loss."""
        await storage.create_wallet("precision-test", initial_balance=9.99)
        wallet = await storage.get_wallet("precision-test")
        assert wallet["balance"] == 9.99
        # Verify the raw integer value is exact
        cursor = await storage.db.execute(
            "SELECT balance FROM wallets WHERE agent_id = 'precision-test'"
        )
        row = await cursor.fetchone()
        assert row[0] == 999_000_000  # Exact!

    async def test_atomic_debit_with_integer(self, storage):
        """Atomic debit should work correctly with integer storage."""
        await storage.create_wallet("debit-test", initial_balance=100.0)
        success, balance = await storage.atomic_debit_strict("debit-test", 0.01)
        assert success is True
        assert abs(balance - 99.99) < 1e-10

    async def test_sum_cost_with_integer(self, storage):
        """SUM(cost) should work correctly with integer storage."""
        await storage.create_wallet("sum-test")
        await storage.record_usage("sum-test", "tool_a", cost=0.01)
        await storage.record_usage("sum-test", "tool_b", cost=0.02)
        await storage.record_usage("sum-test", "tool_c", cost=0.03)
        total = await storage.sum_cost_since("sum-test", 0.0)
        assert abs(total - 0.06) < 1e-10
