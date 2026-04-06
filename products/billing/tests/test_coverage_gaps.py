"""Targeted tests for uncovered code paths in billing/*.

These tests fill in the coverage gaps for:
- storage.py: atomic_debit (legacy API), idempotency-key lookups, budget caps,
  wallet-freeze, currency balance edge cases, and the org-wallet suite.
- wallet.py: frozen-wallet errors, idempotency-key short-circuits, and
  convert_currency pre-flight checks.
- models.py: Decimal field serializers (amount, rate).
- pricing.py: get_discount_tier wrapper.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src.models import CurrencyAmount, ExchangeRate
from src.storage import StorageBackend
from src.wallet import (
    InsufficientCreditsError,
    Wallet,
    WalletFrozenError,
    WalletNotFoundError,
)

# ---------------------------------------------------------------------------
# storage.py — legacy / edge-case paths
# ---------------------------------------------------------------------------


class TestAtomicDebitLegacy:
    async def test_sufficient_balance_returns_new_balance(self, storage: StorageBackend):
        await storage.create_wallet("agent-ad", 100.0)
        new_balance = await storage.atomic_debit("agent-ad", 30.0)
        assert new_balance == 70.0

    async def test_insufficient_balance_does_not_change(self, storage: StorageBackend):
        await storage.create_wallet("agent-ad2", 10.0)
        # Debit that would go negative: UPDATE matches zero rows, balance unchanged.
        new_balance = await storage.atomic_debit("agent-ad2", 100.0)
        assert new_balance == 10.0

    async def test_missing_wallet_returns_none(self, storage: StorageBackend):
        new_balance = await storage.atomic_debit("nope", 1.0)
        assert new_balance is None


class TestAtomicStrictMissingWallet:
    async def test_debit_strict_missing_wallet(self, storage: StorageBackend):
        ok, bal = await storage.atomic_debit_strict("ghost", 1.0)
        assert ok is False
        assert bal == 0.0

    async def test_credit_missing_wallet_returns_false_zero(self, storage: StorageBackend):
        ok, bal = await storage.atomic_credit("ghost", 1.0)
        assert ok is False
        assert bal == 0.0


class TestIdempotencyLookup:
    async def test_get_transaction_by_idempotency_key_found(self, storage: StorageBackend):
        await storage.create_wallet("agent-idem", 0.0)
        await storage.record_transaction(
            "agent-idem",
            5.0,
            "deposit",
            description="x",
            idempotency_key="k-123",
            result_snapshot='{"new_balance":5.0}',
        )
        found = await storage.get_transaction_by_idempotency_key("k-123")
        assert found is not None
        assert found["idempotency_key"] == "k-123"
        # stored as atomic units then converted back
        assert found["amount"] == 5.0

    async def test_get_transaction_by_idempotency_key_missing(self, storage: StorageBackend):
        assert await storage.get_transaction_by_idempotency_key("nope") is None


class TestUsageQueryRanges:
    async def test_get_usage_with_until_filter(self, storage: StorageBackend):
        import time as _time

        await storage.create_wallet("agent-u", 0.0)
        t0 = _time.time()
        await storage.record_usage("agent-u", "fn", 1.0)
        # until earlier than now → excludes everything
        rows = await storage.get_usage("agent-u", until=t0 - 1000)
        assert rows == []
        # until in the future → includes record
        rows = await storage.get_usage("agent-u", until=t0 + 1000)
        assert len(rows) == 1

    async def test_get_usage_summary_no_wallet_still_returns_zeros(self, storage: StorageBackend):
        # No wallet, no usage_records rows — COUNT(*) returns 0, SUMs return 0.
        summary = await storage.get_usage_summary("phantom")
        assert summary["total_calls"] == 0
        assert summary["total_cost"] == 0.0
        assert summary["total_tokens"] == 0


class TestBudgetCaps:
    async def test_set_and_get_budget_cap(self, storage: StorageBackend):
        await storage.set_budget_cap("agent-bc", daily_cap=10.0, monthly_cap=100.0, alert_threshold=0.5)
        cap = await storage.get_budget_cap("agent-bc")
        assert cap is not None
        assert cap["daily_cap"] == 10.0
        assert cap["monthly_cap"] == 100.0
        assert cap["alert_threshold"] == 0.5

    async def test_get_budget_cap_missing_returns_none(self, storage: StorageBackend):
        assert await storage.get_budget_cap("no-bc") is None

    async def test_set_budget_cap_upsert(self, storage: StorageBackend):
        await storage.set_budget_cap("agent-bc2", daily_cap=1.0)
        await storage.set_budget_cap("agent-bc2", daily_cap=2.0, monthly_cap=20.0)
        cap = await storage.get_budget_cap("agent-bc2")
        assert cap["daily_cap"] == 2.0
        assert cap["monthly_cap"] == 20.0

    async def test_delete_budget_cap(self, storage: StorageBackend):
        await storage.set_budget_cap("agent-bc3", daily_cap=1.0)
        await storage.delete_budget_cap("agent-bc3")
        assert await storage.get_budget_cap("agent-bc3") is None

    async def test_set_budget_cap_with_nulls(self, storage: StorageBackend):
        # Both caps None → atomic converters skipped (daily_atomic / monthly_atomic = None).
        await storage.set_budget_cap("agent-bc4", daily_cap=None, monthly_cap=None)
        cap = await storage.get_budget_cap("agent-bc4")
        assert cap is not None
        assert cap["daily_cap"] is None
        assert cap["monthly_cap"] is None


class TestWalletFreeze:
    async def test_is_wallet_frozen_default_false(self, storage: StorageBackend):
        assert await storage.is_wallet_frozen("new-agent") is False

    async def test_set_and_unset_frozen(self, storage: StorageBackend):
        await storage.create_wallet("agent-fr", 0.0)
        await storage.set_wallet_frozen("agent-fr", True)
        assert await storage.is_wallet_frozen("agent-fr") is True
        await storage.set_wallet_frozen("agent-fr", False)
        assert await storage.is_wallet_frozen("agent-fr") is False


class TestGetCurrencyBalanceEdges:
    async def test_credits_missing_wallet_returns_zero(self, storage: StorageBackend):
        assert await storage.get_currency_balance("ghost", "CREDITS") == 0.0

    async def test_noncredits_missing_currency_returns_zero(self, storage: StorageBackend):
        await storage.create_wallet("agent-cb", 0.0)
        assert await storage.get_currency_balance("agent-cb", "USD") == 0.0


# ---------------------------------------------------------------------------
# storage.py — organization wallets
# ---------------------------------------------------------------------------


class TestOrgWallets:
    async def test_create_and_get_org_wallet(self, storage: StorageBackend):
        # initial_balance here is atomic units (see docstring)
        w = await storage.create_org_wallet("org-1", initial_balance=1_000_000)
        assert w["org_id"] == "org-1"
        assert w["balance"] == storage._from_atomic(1_000_000)
        got = await storage.get_org_wallet("org-1")
        assert got is not None
        assert got["org_id"] == "org-1"

    async def test_get_org_wallet_missing(self, storage: StorageBackend):
        assert await storage.get_org_wallet("no-org") is None

    async def test_atomic_org_credit_and_debit(self, storage: StorageBackend):
        await storage.create_org_wallet("org-2", initial_balance=1000)
        ok, bal = await storage.atomic_org_credit("org-2", 500)
        assert ok is True
        assert bal == storage._from_atomic(1500)

        ok, bal = await storage.atomic_org_debit_strict("org-2", 200)
        assert ok is True
        assert bal == storage._from_atomic(1300)

        # Over-debit returns (False, current) — UPDATE matches zero rows.
        ok, bal = await storage.atomic_org_debit_strict("org-2", 10_000_000)
        assert ok is False
        assert bal == storage._from_atomic(1300)

    async def test_atomic_org_ops_missing_wallet(self, storage: StorageBackend):
        ok, bal = await storage.atomic_org_credit("ghost-org", 1)
        assert ok is False
        assert bal == 0.0

        ok, bal = await storage.atomic_org_debit_strict("ghost-org", 1)
        assert ok is False
        assert bal == 0.0

    async def test_org_member_register_and_get(self, storage: StorageBackend):
        await storage.create_org_wallet("org-3", 0)
        await storage.register_org_member("org-3", "agent-x", role="member", spend_limit_atomic=1_000)
        m = await storage.get_org_member("org-3", "agent-x")
        assert m is not None
        assert m["role"] == "member"
        assert m["spend_limit"] == storage._from_atomic(1_000)

    async def test_org_member_get_missing(self, storage: StorageBackend):
        assert await storage.get_org_member("no-org", "no-agent") is None

    async def test_org_member_without_spend_limit(self, storage: StorageBackend):
        await storage.create_org_wallet("org-4", 0)
        await storage.register_org_member("org-4", "agent-y", "admin")
        m = await storage.get_org_member("org-4", "agent-y")
        assert m is not None
        assert m["spend_limit"] is None

    async def test_org_transactions_and_member_spending(self, storage: StorageBackend):
        await storage.create_org_wallet("org-5", 0)
        tx_id = await storage.record_org_transaction(
            "org-5", "agent-a", amount_atomic=-100, tx_type="charge", description="x"
        )
        assert isinstance(tx_id, int) and tx_id > 0
        await storage.record_org_transaction("org-5", "agent-a", amount_atomic=-50, tx_type="charge")
        await storage.record_org_transaction("org-5", "agent-b", amount_atomic=-20, tx_type="charge")
        # Non-"charge" rows must be excluded.
        await storage.record_org_transaction("org-5", "agent-a", amount_atomic=5, tx_type="refund")

        all_spend = await storage.get_org_member_spending("org-5")
        by_agent = {r["agent_id"]: r["total_spent"] for r in all_spend}
        assert by_agent["agent-a"] == storage._from_atomic(150)
        assert by_agent["agent-b"] == storage._from_atomic(20)

        filtered = await storage.get_org_member_spending("org-5", agent_id="agent-a")
        assert len(filtered) == 1
        assert filtered[0]["total_spent"] == storage._from_atomic(150)


# ---------------------------------------------------------------------------
# wallet.py — error paths + idempotency short-circuits
# ---------------------------------------------------------------------------


class TestWalletFrozenError:
    def test_exception_holds_agent_id(self):
        exc = WalletFrozenError("agent-X")
        assert exc.agent_id == "agent-X"
        assert "agent-X" in str(exc)


class TestGetBalanceMissingWallet:
    async def test_credits_missing_wallet_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        with pytest.raises(WalletNotFoundError):
            await w.get_balance("no-one")

    async def test_noncredits_missing_wallet_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        with pytest.raises(WalletNotFoundError):
            await w.get_balance("no-one", currency="USD")


class TestDepositWithdrawFrozen:
    async def test_deposit_on_frozen_wallet_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-fd", initial_balance=10.0, signup_bonus=False)
        await storage.set_wallet_frozen("agent-fd", True)
        with pytest.raises(WalletFrozenError):
            await w.deposit("agent-fd", 1.0)

    async def test_withdraw_on_frozen_wallet_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-fw", initial_balance=10.0, signup_bonus=False)
        await storage.set_wallet_frozen("agent-fw", True)
        with pytest.raises(WalletFrozenError):
            await w.withdraw("agent-fw", 1.0)


class TestIdempotentDepositWithdraw:
    async def test_deposit_replay_returns_snapshot_balance(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-id", initial_balance=0.0, signup_bonus=False)
        bal1 = await w.deposit("agent-id", 5.0, idempotency_key="K1")
        assert bal1 == 5.0
        # Replay same key — should NOT double-credit, returns cached balance.
        bal2 = await w.deposit("agent-id", 999.0, idempotency_key="K1")
        assert bal2 == bal1
        # Confirm only one deposit was recorded.
        txns = await storage.get_transactions("agent-id")
        deposits = [t for t in txns if t["idempotency_key"] == "K1"]
        assert len(deposits) == 1

    async def test_withdraw_replay_returns_snapshot_balance(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-iw", initial_balance=10.0, signup_bonus=False)
        bal1 = await w.withdraw("agent-iw", 3.0, idempotency_key="W1")
        assert bal1 == 7.0
        bal2 = await w.withdraw("agent-iw", 999.0, idempotency_key="W1")
        assert bal2 == bal1
        # Only one withdrawal with the key.
        txns = await storage.get_transactions("agent-iw")
        withdrawals = [t for t in txns if t["idempotency_key"] == "W1"]
        assert len(withdrawals) == 1

    async def test_deposit_idempotency_without_snapshot_uses_current_balance(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-in", initial_balance=5.0, signup_bonus=False)
        # Insert a transaction row with idempotency_key but NO result_snapshot.
        await storage.record_transaction("agent-in", 0.0, "deposit", idempotency_key="LEGACY", result_snapshot=None)
        bal = await w.deposit("agent-in", 100.0, idempotency_key="LEGACY")
        assert bal == 5.0  # current balance, no double-credit

    async def test_withdraw_idempotency_without_snapshot_uses_current_balance(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-wn", initial_balance=20.0, signup_bonus=False)
        await storage.record_transaction("agent-wn", 0.0, "withdrawal", idempotency_key="LEGACY2", result_snapshot=None)
        bal = await w.withdraw("agent-wn", 100.0, idempotency_key="LEGACY2")
        assert bal == 20.0


class TestWithdrawInsufficient:
    async def test_withdraw_more_than_balance_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-ins", initial_balance=1.0, signup_bonus=False)
        with pytest.raises(InsufficientCreditsError):
            await w.withdraw("agent-ins", 100.0)


class TestConvertCurrencyPreFlight:
    async def test_amount_must_be_positive(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        with pytest.raises(ValueError, match="positive"):
            await w.convert_currency("any", 0.0, "USD", "CREDITS", exchange_service=None)

    async def test_frozen_wallet_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-cv1", initial_balance=10.0, signup_bonus=False)
        await storage.set_wallet_frozen("agent-cv1", True)
        with pytest.raises(WalletFrozenError):
            await w.convert_currency("agent-cv1", 1.0, "USD", "CREDITS", exchange_service=None)

    async def test_missing_wallet_raises(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        with pytest.raises(WalletNotFoundError):
            await w.convert_currency("ghost-cv", 1.0, "USD", "CREDITS", exchange_service=None)


class TestAutoReloadFailurePath:
    async def test_auto_reload_no_config_returns_current(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-ar1", initial_balance=10.0, signup_bonus=False)
        # No auto-reload config: _maybe_auto_reload returns current balance unchanged.
        assert await w._maybe_auto_reload("agent-ar1", 3.0) == 3.0

    async def test_auto_reload_above_threshold_does_nothing(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        await w.create("agent-ar2", initial_balance=100.0, signup_bonus=False)
        await w.enable_auto_reload("agent-ar2", threshold=10.0, reload_amount=50.0)
        # current_balance=20 >= threshold=10 → no reload.
        assert await w._maybe_auto_reload("agent-ar2", 20.0) == 20.0

    async def test_auto_reload_missing_wallet_returns_current_balance(self, storage: StorageBackend):
        # Configure for an agent that has a config row but no wallet row →
        # atomic_credit returns (False, 0.0), and _maybe_auto_reload returns
        # the original current_balance.
        await storage.set_auto_reload("ghost-ar", threshold=10.0, reload_amount=5.0, enabled=True)
        w = Wallet(storage=storage)
        assert await w._maybe_auto_reload("ghost-ar", 2.0) == 2.0

    async def test_disable_auto_reload_without_config_is_noop(self, storage: StorageBackend):
        w = Wallet(storage=storage)
        # No existing config → branch where config is None must return cleanly.
        await w.disable_auto_reload("no-config-agent")
        assert await w.get_auto_reload_config("no-config-agent") is None


# ---------------------------------------------------------------------------
# models.py — field serializers
# ---------------------------------------------------------------------------


class TestMoneyRateSerializers:
    def test_currency_amount_serialized_as_str(self):
        m = CurrencyAmount(amount=Decimal("12.345"), currency="USD")
        dumped = m.model_dump()
        assert dumped["amount"] == "12.345"
        assert isinstance(dumped["amount"], str)

    def test_exchange_rate_serialized_as_str(self):
        er = ExchangeRate(
            from_currency="USD",
            to_currency="CREDITS",
            rate=Decimal("100.5"),
            updated_at=0.0,
        )
        dumped = er.model_dump()
        assert dumped["rate"] == "100.5"
        assert isinstance(dumped["rate"], str)


# ---------------------------------------------------------------------------
# pricing.py — thin wrapper exists for gateway / billing routes
# ---------------------------------------------------------------------------


class TestPricingWrapper:
    def test_get_discount_tier_returns_int(self):
        from src.pricing import get_discount_tier

        result = get_discount_tier(0)
        assert isinstance(result, int)
        assert 0 <= result <= 100


# ---------------------------------------------------------------------------
# storage.py — BEGIN IMMEDIATE rollback paths
# ---------------------------------------------------------------------------


class TestAtomicRollbackPaths:
    """Ensure rollback is called when an exception occurs inside a transaction."""

    async def test_atomic_credit_rollback_on_error(self, storage: StorageBackend, monkeypatch):
        """atomic_credit rolls back and re-raises on exception inside txn."""
        await storage.create_wallet("rollback-credit", initial_balance=100.0)
        call_count = 0
        _orig = storage.db.execute

        async def _patched(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 3:  # Third execute (UPDATE) — raise error
                raise RuntimeError("simulated DB error")
            if params:
                return await _orig(sql, params)
            return await _orig(sql)

        monkeypatch.setattr(storage.db, "execute", _patched)
        with pytest.raises(RuntimeError, match="simulated DB error"):
            await storage.atomic_credit("rollback-credit", 10.0)

    async def test_atomic_debit_rollback_on_error(self, storage: StorageBackend, monkeypatch):
        """atomic_debit rolls back and re-raises on exception inside txn."""
        await storage.create_wallet("rollback-debit", initial_balance=100.0)
        call_count = 0
        _orig = storage.db.execute

        async def _patched(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("simulated DB error")
            if params:
                return await _orig(sql, params)
            return await _orig(sql)

        monkeypatch.setattr(storage.db, "execute", _patched)
        with pytest.raises(RuntimeError, match="simulated DB error"):
            await storage.atomic_debit("rollback-debit", 10.0)

    async def test_atomic_debit_strict_rollback_on_error(self, storage: StorageBackend, monkeypatch):
        """atomic_debit_strict rolls back and re-raises on exception inside txn."""
        await storage.create_wallet("rollback-debit-strict", initial_balance=100.0)
        call_count = 0
        _orig = storage.db.execute

        async def _patched(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("simulated DB error")
            if params:
                return await _orig(sql, params)
            return await _orig(sql)

        monkeypatch.setattr(storage.db, "execute", _patched)
        with pytest.raises(RuntimeError, match="simulated DB error"):
            await storage.atomic_debit_strict("rollback-debit-strict", 10.0)

    async def test_atomic_currency_credit_rollback_on_error(self, storage: StorageBackend, monkeypatch):
        """atomic_currency_credit (non-CREDITS) rolls back on error."""
        await storage.create_wallet("rollback-curr-credit", initial_balance=100.0)
        call_count = 0
        _orig = storage.db.execute

        async def _patched(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("simulated DB error")
            if params:
                return await _orig(sql, params)
            return await _orig(sql)

        monkeypatch.setattr(storage.db, "execute", _patched)
        with pytest.raises(RuntimeError, match="simulated DB error"):
            await storage.atomic_currency_credit("rollback-curr-credit", 10.0, "USD")

    async def test_atomic_currency_debit_strict_rollback_on_error(self, storage: StorageBackend, monkeypatch):
        """atomic_currency_debit_strict (non-CREDITS) rolls back on error."""
        await storage.create_wallet("rollback-curr-debit", initial_balance=100.0)
        # First credit some USD so debit has something to work with
        await storage.atomic_currency_credit("rollback-curr-debit", 50.0, "USD")
        call_count = 0
        _orig = storage.db.execute

        async def _patched(sql, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise RuntimeError("simulated DB error")
            if params:
                return await _orig(sql, params)
            return await _orig(sql)

        monkeypatch.setattr(storage.db, "execute", _patched)
        with pytest.raises(RuntimeError, match="simulated DB error"):
            await storage.atomic_currency_debit_strict("rollback-curr-debit", 10.0, "USD")
