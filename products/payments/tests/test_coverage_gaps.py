"""Tests targeting specific uncovered lines in payments/ to raise coverage to 95%+.

Focus areas:
- PaymentEngine: idempotency replay short-circuits, partial_capture (entirely uncovered),
  DuplicateIntentError, not-found error paths for expire/suspend/charge.
- PaymentStorage: idempotency lookup helpers, update_subscription metadata/amount
  serialization, update_intent_amount, get_due_subscriptions default-now.
- PlanManager: metadata-as-string JSON path, process_due failure path.
- SubscriptionScheduler: non-InsufficientCreditsError failure path, run-loop exception path.
- payments/__init__.py: re-export smoke test.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from payments.engine import (
    DuplicateIntentError,
    EscrowNotFoundError,
    InvalidStateError,
    PaymentError,
    SubscriptionNotFoundError,
)
from payments.models import (
    EscrowStatus,
    IntentStatus,
    PaymentIntent,
    SubscriptionStatus,
)

# ---------------------------------------------------------------------------
# DuplicateIntentError (engine.py lines 63-65)
# ---------------------------------------------------------------------------


class TestDuplicateIntentError:
    def test_exception_holds_existing_intent_and_message(self):
        intent = PaymentIntent(payer="a", payee="b", amount=1.0)
        err = DuplicateIntentError(existing_intent=intent)
        assert err.existing_intent is intent
        assert intent.id in str(err)


# ---------------------------------------------------------------------------
# Idempotency replay short-circuits — engine level
# ---------------------------------------------------------------------------


class TestIdempotencyReplay:
    async def test_create_intent_idempotency_returns_existing(self, engine, funded_wallets):
        key = "idem-create-1"
        first = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0, idempotency_key=key)
        second = await engine.create_intent(payer="agent-a", payee="agent-b", amount=99.0, idempotency_key=key)
        assert second.id == first.id
        assert second.amount == first.amount  # original amount, not 99

    async def test_capture_idempotency_returns_existing_settlement(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        key = "idem-capture-1"
        s1 = await engine.capture(intent.id, idempotency_key=key)
        # Second call: short-circuits via get_settlement_by_idempotency_key
        # (doesn't even look at intent_id)
        s2 = await engine.capture("nonexistent-id", idempotency_key=key)
        assert s2.id == s1.id
        assert s2.amount == s1.amount

    async def test_void_idempotency_returns_already_voided(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        await engine.void(intent.id)
        # Same idempotency_key on already-voided intent returns as-is
        result = await engine.void(intent.id, idempotency_key="idem-void-1")
        assert result.status == IntentStatus.VOIDED

    async def test_refund_settlement_idempotency_returns_existing(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=20.0)
        settlement = await engine.capture(intent.id)
        key = "idem-refund-1"
        r1 = await engine.refund_settlement(settlement.id, idempotency_key=key)
        r2 = await engine.refund_settlement(settlement.id, idempotency_key=key)
        assert r2.id == r1.id
        assert r2.amount == r1.amount

    async def test_create_escrow_idempotency_returns_existing(self, engine, funded_wallets):
        key = "idem-escrow-1"
        e1 = await engine.create_escrow(payer="agent-a", payee="agent-b", amount=15.0, idempotency_key=key)
        e2 = await engine.create_escrow(payer="agent-a", payee="agent-b", amount=999.0, idempotency_key=key)
        assert e2.id == e1.id
        assert e2.amount == e1.amount

    async def test_release_escrow_idempotency_returns_existing_settlement(self, engine, funded_wallets):
        escrow = await engine.create_escrow(payer="agent-a", payee="agent-b", amount=20.0)
        key = "idem-release-1"
        s1 = await engine.release_escrow(escrow.id, idempotency_key=key)
        s2 = await engine.release_escrow("nonexistent-id", idempotency_key=key)
        assert s2.id == s1.id

    async def test_refund_escrow_idempotency_returns_already_refunded(self, engine, funded_wallets):
        escrow = await engine.create_escrow(payer="agent-a", payee="agent-b", amount=20.0)
        await engine.refund_escrow(escrow.id)
        # Already refunded + idempotency_key = return as-is
        result = await engine.refund_escrow(escrow.id, idempotency_key="idem-refund-escrow-1")
        assert result.status == EscrowStatus.REFUNDED

    async def test_create_subscription_idempotency_returns_existing(self, engine, funded_wallets):
        key = "idem-sub-1"
        s1 = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=5.0, interval="daily", idempotency_key=key
        )
        s2 = await engine.create_subscription(
            payer="agent-a", payee="agent-b", amount=999.0, interval="weekly", idempotency_key=key
        )
        assert s2.id == s1.id
        assert s2.amount == s1.amount

    async def test_reactivate_subscription_idempotency_on_already_active(self, engine, funded_wallets):
        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=5.0, interval="daily")
        # Active + idempotency_key = return as-is (no state change required)
        result = await engine.reactivate_subscription(sub.id, idempotency_key="idem-react-1")
        assert result.status == SubscriptionStatus.ACTIVE


# ---------------------------------------------------------------------------
# partial_capture — engine.py lines 197-267 (fully uncovered)
# ---------------------------------------------------------------------------


class TestPartialCapture:
    async def test_partial_capture_transfers_funds_and_keeps_remaining(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        settlement, remaining = await engine.partial_capture(intent.id, amount=4.0)

        assert settlement.amount == 4.0
        assert remaining == pytest.approx(6.0)

        assert await wallet.get_balance("agent-a") == pytest.approx(996.0)
        assert await wallet.get_balance("agent-b") == pytest.approx(504.0)

        # Intent is still pending with remaining amount
        updated = await engine.get_intent(intent.id)
        assert updated.status == IntentStatus.PENDING
        assert float(updated.amount) == pytest.approx(6.0)

    async def test_partial_capture_full_amount_marks_settled(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        settlement, remaining = await engine.partial_capture(intent.id, amount=10.0)
        assert settlement.amount == 10.0
        assert remaining == 0.0
        updated = await engine.get_intent(intent.id)
        assert updated.status == IntentStatus.SETTLED
        assert updated.settlement_id == settlement.id

    async def test_partial_capture_idempotency_replay(self, engine, funded_wallets):
        wallet, _, _ = funded_wallets
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        key = "idem-partial-1"
        s1, rem1 = await engine.partial_capture(intent.id, amount=3.0, idempotency_key=key)
        # Replay: funds must not move twice
        s2, rem2 = await engine.partial_capture(intent.id, amount=3.0, idempotency_key=key)
        assert s2.id == s1.id
        # Remaining recomputed from current intent (7.0 after first partial)
        assert rem2 == pytest.approx(7.0)
        assert await wallet.get_balance("agent-a") == pytest.approx(997.0)
        assert await wallet.get_balance("agent-b") == pytest.approx(503.0)

    async def test_partial_capture_idempotency_replay_intent_missing(self, engine, funded_wallets):
        """When intent no longer exists during replay, remaining == 0.0."""
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        key = "idem-partial-missing"
        await engine.partial_capture(intent.id, amount=10.0, idempotency_key=key)
        # After full partial_capture the intent row still exists, so bypass via
        # the second branch: replay with a fake intent id that doesn't exist.
        # The short-circuit uses settlement_by_idempotency_key first, then looks
        # up the intent by the passed-in id. If that id has no row, remaining = 0.0.
        s, rem = await engine.partial_capture("does-not-exist", amount=10.0, idempotency_key=key)
        assert rem == 0.0
        assert s.amount == 10.0

    async def test_partial_capture_intent_not_found(self, engine, funded_wallets):
        from payments.engine import IntentNotFoundError

        with pytest.raises(IntentNotFoundError):
            await engine.partial_capture("nonexistent", amount=5.0)

    async def test_partial_capture_non_pending_intent(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        await engine.void(intent.id)
        with pytest.raises(InvalidStateError, match="voided"):
            await engine.partial_capture(intent.id, amount=5.0)

    async def test_partial_capture_amount_must_be_positive(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        with pytest.raises(PaymentError, match="positive"):
            await engine.partial_capture(intent.id, amount=0)
        with pytest.raises(PaymentError, match="positive"):
            await engine.partial_capture(intent.id, amount=-1.0)

    async def test_partial_capture_amount_exceeds_intent(self, engine, funded_wallets):
        intent = await engine.create_intent(payer="agent-a", payee="agent-b", amount=10.0)
        with pytest.raises(PaymentError, match="exceeds intent amount"):
            await engine.partial_capture(intent.id, amount=11.0)


# ---------------------------------------------------------------------------
# Not-found error paths
# ---------------------------------------------------------------------------


class TestNotFoundPaths:
    async def test_expire_escrow_not_found(self, engine):
        with pytest.raises(EscrowNotFoundError):
            await engine.expire_escrow("nonexistent-escrow")

    async def test_suspend_subscription_not_found(self, engine):
        with pytest.raises(SubscriptionNotFoundError):
            await engine.suspend_subscription("nonexistent-sub")

    async def test_charge_subscription_not_found(self, engine):
        with pytest.raises(SubscriptionNotFoundError):
            await engine.charge_subscription("nonexistent-sub")

    async def test_reactivate_subscription_not_found(self, engine):
        with pytest.raises(SubscriptionNotFoundError):
            await engine.reactivate_subscription("nonexistent-sub")


# ---------------------------------------------------------------------------
# Storage idempotency helpers — return None for missing keys
# ---------------------------------------------------------------------------


class TestStorageIdempotencyLookupMiss:
    async def test_get_escrow_by_idempotency_key_missing(self, payment_storage):
        assert await payment_storage.get_escrow_by_idempotency_key("no-such-key") is None

    async def test_get_subscription_by_idempotency_key_missing(self, payment_storage):
        assert await payment_storage.get_subscription_by_idempotency_key("no-such-key") is None

    async def test_get_settlement_by_idempotency_key_missing(self, payment_storage):
        assert await payment_storage.get_settlement_by_idempotency_key("no-such-key") is None

    async def test_get_refund_by_idempotency_key_missing(self, payment_storage):
        assert await payment_storage.get_refund_by_idempotency_key("no-such-key") is None

    async def test_get_due_subscriptions_uses_now_when_none(self, payment_storage):
        # Covers the `if now is None: now = time.time()` default branch
        result = await payment_storage.get_due_subscriptions()
        assert result == []


# ---------------------------------------------------------------------------
# update_subscription — metadata serialization & amount conversion
# ---------------------------------------------------------------------------


class TestUpdateSubscription:
    async def test_update_subscription_metadata_serialized(self, engine, funded_wallets):
        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=5.0, interval="daily")
        await engine.storage.update_subscription(sub.id, {"metadata": {"replaced": True, "currency": "CREDITS"}})
        reloaded = await engine.storage.get_subscription(sub.id)
        assert reloaded["metadata"]["replaced"] is True

    async def test_update_subscription_amount_float_converted(self, engine, funded_wallets):
        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=5.0, interval="daily")
        await engine.storage.update_subscription(sub.id, {"amount": 12.5})
        reloaded = await engine.storage.get_subscription(sub.id)
        assert reloaded["amount"] == pytest.approx(12.5)

    async def test_update_subscription_amount_decimal_converted(self, engine, funded_wallets):
        from decimal import Decimal

        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=5.0, interval="daily")
        await engine.storage.update_subscription(sub.id, {"amount": Decimal("7.25")})
        reloaded = await engine.storage.get_subscription(sub.id)
        assert reloaded["amount"] == pytest.approx(7.25)

    async def test_update_subscription_rejects_invalid_column(self, engine, funded_wallets):
        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=5.0, interval="daily")
        with pytest.raises(ValueError, match="Invalid column"):
            await engine.storage.update_subscription(sub.id, {"rogue_column": "x"})


# ---------------------------------------------------------------------------
# PlanManager — metadata-as-string JSON decoding & failure path
# ---------------------------------------------------------------------------


class TestPlanManagerCoverage:
    async def test_get_active_plan_handles_metadata_as_json_string(self, engine, billing_wallet, funded_wallets):
        """When SQLite returns metadata as JSON string (possible via direct ops),
        _get_active_subscription must decode it."""
        from payments.plans import PlanManager

        mgr = PlanManager(engine=engine, wallet=billing_wallet)

        # Insert a subscription directly with metadata as a JSON string
        import json
        import time as time_mod
        import uuid

        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        now = time_mod.time()
        meta = json.dumps({"type": "plan_subscription", "plan_id": "free", "credits_per_cycle": 100})
        await engine.storage.db.execute(
            "INSERT INTO subscriptions "
            "(id, payer, payee, amount, interval, description, status, cancelled_by, "
            "next_charge_at, last_charged_at, charge_count, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sub_id,
                "platform",
                "agent-a",
                100_00000000,
                "monthly",
                "",
                "active",
                None,
                now + 86400,
                None,
                0,
                now,
                now,
                meta,
            ),
        )
        await engine.storage.db.commit()

        active = await mgr.get_active_plan("agent-a")
        assert active is not None
        assert active["plan_id"] == "free"

    async def test_process_due_skips_non_plan_subscriptions(self, engine, billing_wallet, funded_wallets):
        """process_due() must skip regular (non-plan) subscriptions via metadata check."""
        from payments.plans import PlanManager

        mgr = PlanManager(engine=engine, wallet=billing_wallet)

        # Create a regular subscription (not a plan_subscription)
        import time as time_mod

        past = time_mod.time() - 10
        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=1.0, interval="daily")
        await engine.storage.update_subscription(sub.id, {"next_charge_at": past})
        # Process — should skip this one entirely (metadata lacks type=plan_subscription)
        result = await mgr.process_due()
        assert result.processed == 0

    async def test_get_active_plan_metadata_as_string_branch(self, engine, billing_wallet, monkeypatch):
        """Patch storage.list_subscriptions to return metadata as JSON string,
        exercising the isinstance(metadata, str) JSON-decode branch."""
        from payments.plans import PlanManager

        mgr = PlanManager(engine=engine, wallet=billing_wallet)

        async def fake_list(*args, **kwargs):
            import json
            import time as time_mod

            now = time_mod.time()
            # metadata as JSON string; after decode, type != plan_subscription,
            # so loop continues and _get_active_subscription returns None.
            return [
                {
                    "id": "sub_raw",
                    "payer": "agent-a",
                    "payee": "agent-b",
                    "amount": 5.0,
                    "interval": "daily",
                    "description": "",
                    "idempotency_key": None,
                    "status": "active",
                    "cancelled_by": None,
                    "next_charge_at": now + 86400,
                    "last_charged_at": None,
                    "charge_count": 0,
                    "created_at": now,
                    "updated_at": now,
                    "metadata": json.dumps({"type": "regular_sub"}),
                }
            ]

        monkeypatch.setattr(engine.storage, "list_subscriptions", fake_list)

        active = await mgr.get_active_plan("agent-a")
        assert active is None  # no plan_subscription, so None

    async def test_process_due_metadata_as_string_branch(self, engine, billing_wallet, monkeypatch):
        """Patch storage.get_due_subscriptions to return metadata as JSON string,
        exercising the isinstance(metadata, str) branch in process_due()."""
        from payments.plans import PlanManager

        mgr = PlanManager(engine=engine, wallet=billing_wallet)

        async def fake_due(*args, **kwargs):
            import json
            import time as time_mod

            now = time_mod.time()
            # Return metadata as raw JSON string — triggers line 145-147
            # Also a row where metadata.type != plan_subscription after decode — triggers `continue` on 149
            return [
                {
                    "id": "sub_raw_skip",
                    "payer": "agent-a",
                    "payee": "agent-b",
                    "amount": 5.0,
                    "interval": "daily",
                    "description": "",
                    "idempotency_key": None,
                    "status": "active",
                    "cancelled_by": None,
                    "next_charge_at": now - 10,
                    "last_charged_at": None,
                    "charge_count": 0,
                    "created_at": now,
                    "updated_at": now,
                    "metadata": json.dumps({"type": "regular"}),
                }
            ]

        monkeypatch.setattr(engine.storage, "get_due_subscriptions", fake_due)
        result = await mgr.process_due()
        assert result.processed == 0  # skipped via continue

    async def test_process_due_failure_path_records_error(self, engine, billing_wallet, monkeypatch):
        """If a deposit raises, process_due records the failure in results."""
        from payments.plans import PlanManager

        # Break the wallet.deposit to raise
        async def broken_deposit(*args, **kwargs):
            raise RuntimeError("wallet offline")

        monkeypatch.setattr(billing_wallet, "deposit", broken_deposit)

        # Bypass subscribe (which grants initial credits) — insert directly
        import json
        import time as time_mod
        import uuid

        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        now = time_mod.time()
        meta = json.dumps({"type": "plan_subscription", "plan_id": "free", "credits_per_cycle": 50})
        await engine.storage.db.execute(
            "INSERT INTO subscriptions "
            "(id, payer, payee, amount, interval, description, status, cancelled_by, "
            "next_charge_at, last_charged_at, charge_count, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sub_id,
                "platform",
                "agent-x",
                50_00000000,
                "monthly",
                "",
                "active",
                None,
                now - 10,
                None,
                0,
                now,
                now,
                meta,
            ),
        )
        await engine.storage.db.commit()

        mgr = PlanManager(engine=engine, wallet=billing_wallet)
        result = await mgr.process_due()
        assert result.processed == 1
        assert result.failed == 1
        assert result.succeeded == 0
        assert "wallet offline" in (result.results[0].error or "")


# ---------------------------------------------------------------------------
# SubscriptionScheduler — non-InsufficientCredits exception + run() loop
# ---------------------------------------------------------------------------


class TestSchedulerCoverage:
    async def test_process_due_records_generic_failure(self, scheduler, engine, funded_wallets, monkeypatch):
        sub = await engine.create_subscription(payer="agent-a", payee="agent-b", amount=1.0, interval="daily")
        import time as time_mod

        await engine.storage.update_subscription(sub.id, {"next_charge_at": time_mod.time() - 10})

        # Make charge_subscription raise a non-InsufficientCreditsError
        async def bad_charge(_sub_id):
            raise RuntimeError("boom")

        monkeypatch.setattr(engine, "charge_subscription", bad_charge)

        result = await scheduler.process_due()
        assert result.processed == 1
        assert result.failed == 1
        assert result.succeeded == 0
        assert "boom" in (result.results[0].error or "")

    async def test_process_due_skips_plan_subscriptions(self, scheduler, engine, funded_wallets):
        """Scheduler skips rows whose metadata.type == plan_subscription."""
        # Insert a plan subscription row that would be due
        import json
        import time as time_mod
        import uuid

        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        now = time_mod.time()
        meta = json.dumps({"type": "plan_subscription", "plan_id": "free"})
        await engine.storage.db.execute(
            "INSERT INTO subscriptions "
            "(id, payer, payee, amount, interval, description, status, cancelled_by, "
            "next_charge_at, last_charged_at, charge_count, created_at, updated_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sub_id,
                "platform",
                "agent-a",
                100_00000000,
                "monthly",
                "",
                "active",
                None,
                now - 10,
                None,
                0,
                now,
                now,
                meta,
            ),
        )
        await engine.storage.db.commit()

        result = await scheduler.process_due()
        assert result.processed == 0  # plan subscription skipped

    async def test_run_loop_with_max_iterations_handles_exception(self, scheduler, engine, monkeypatch, caplog):
        """run() catches exceptions in process_due and logs them, then continues."""

        async def failing_process(*args, **kwargs):
            raise RuntimeError("scheduler blew up")

        monkeypatch.setattr(scheduler, "process_due", failing_process)

        async def no_sleep(*args, **kwargs):
            return None

        monkeypatch.setattr(asyncio, "sleep", no_sleep)

        with caplog.at_level(logging.ERROR):
            await scheduler.run(interval=0.0, max_iterations=2)
        assert any("Scheduler run failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# payments/__init__.py — re-exports (0% → 100%)
# ---------------------------------------------------------------------------


class TestPackageInit:
    def test_package_init_executes(self):
        """Execute src/__init__.py against the already-registered 'payments'
        virtual package so its re-export lines are covered.

        The conftest.py registers 'payments' in sys.modules as a virtual
        package pointing at src/ without executing __init__.py. Here we read
        the file and exec it in the module's namespace, with relative imports
        resolving to payments.engine/payments.models/etc.
        """
        import os
        import sys

        payments_pkg = sys.modules["payments"]
        init_path = os.path.join(payments_pkg.__path__[0], "__init__.py")
        with open(init_path) as f:
            source = f.read()
        code = compile(source, init_path, "exec")
        exec(code, payments_pkg.__dict__)  # noqa: S102 — covering package init

        assert hasattr(payments_pkg, "PaymentEngine")
        assert hasattr(payments_pkg, "PaymentStorage")
        assert hasattr(payments_pkg, "PaymentIntent")
        assert hasattr(payments_pkg, "Settlement")
        assert hasattr(payments_pkg, "Escrow")
        assert hasattr(payments_pkg, "EscrowStatus")
        assert hasattr(payments_pkg, "IntentStatus")
        assert hasattr(payments_pkg, "Subscription")
        assert hasattr(payments_pkg, "SubscriptionInterval")
        assert hasattr(payments_pkg, "SubscriptionStatus")
        assert isinstance(payments_pkg.__version__, str)
        assert "PaymentEngine" in payments_pkg.__all__
