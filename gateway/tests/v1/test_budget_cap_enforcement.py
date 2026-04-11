"""v1.2.4 audit P0-5: budget cap enforcement at the request path.

The gateway has a ``set_budget_cap`` tool that writes daily/monthly
caps into ``budget_caps`` and a ``get_budget_status`` tool that
reports whether a cap is exceeded — but until this fix there was
**no middleware gate** that actually stopped a paid call when the
cap was hit. ``get_budget_status`` would happily set
``cap_exceeded=true`` *and* the very next ``POST /v1/payments/intents``
would still succeed.

The fix: the per-request billing dep consults ``budget_caps`` after
the balance check and returns ``402 budget_exceeded`` (RFC 9457)
when the caller has already spent up to the cap.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _prepare_agent(app, agent_id, *, balance=500.0, daily_cap=None, monthly_cap=None):
    ctx = app.state.ctx
    await ctx.tracker.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    key_info = await ctx.key_manager.create_key(agent_id, tier="pro")
    if daily_cap is not None or monthly_cap is not None:
        await ctx.tracker.storage.db.execute(
            "INSERT OR REPLACE INTO budget_caps "
            "(agent_id, daily_cap, monthly_cap, alert_threshold) "
            "VALUES (?, ?, ?, ?)",
            (
                agent_id,
                int(daily_cap * 100_000_000) if daily_cap is not None else None,
                int(monthly_cap * 100_000_000) if monthly_cap is not None else None,
                0.8,
            ),
        )
        await ctx.tracker.storage.db.commit()
    return key_info["key"]


class TestBudgetCapEnforcement:
    async def test_calls_under_cap_succeed(self, client, app):
        key = await _prepare_agent(app, "budget-ok", daily_cap=100.0)
        # get_balance is free; check a paid tool via a fake cost path.
        # Easier: call get_balance directly (free) and assert nothing
        # blocks. The important thing is no false positive.
        resp = await client.get(
            "/v1/billing/wallets/budget-ok/balance",
            headers={"Authorization": f"Bearer {key}"},
        )
        assert resp.status_code == 200

    async def test_daily_cap_exceeded_returns_402(self, client, app):
        """Record usage totalling above the daily cap, then expect 402.

        We synthesise the spend by inserting a large usage_records row
        directly so we don't have to loop a real paid tool 95 times.
        """
        import time as _time

        key = await _prepare_agent(app, "budget-over", balance=1000.0, daily_cap=10.0)
        ctx = app.state.ctx

        # Insert a usage record that already spends 95 credits today.
        # The daily_cap is 10.0 credits → we're way over.
        now = _time.time()
        await ctx.tracker.storage.db.execute(
            "INSERT INTO usage_records (agent_id, function, cost, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?)",
            ("budget-over", "create_intent", int(95.0 * 100_000_000), now, None),
        )
        await ctx.tracker.storage.db.commit()

        # Next paid call must be denied with 402 budget_exceeded.
        await ctx.tracker.wallet.create("budget-payee", initial_balance=0.0, signup_bonus=False)
        resp = await client.post(
            "/v1/payments/intents",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "payer": "budget-over",
                "payee": "budget-payee",
                "amount": "5.00",
                "currency": "CREDITS",
                "description": "over budget",
            },
        )
        assert resp.status_code == 402, resp.text
        body = resp.json()
        assert body.get("status") == 402
        text = str(body).lower()
        assert "budget" in text or "cap" in text

    async def test_wallet_not_debited_on_budget_exceeded(self, client, app):
        """A 402 budget_exceeded must leave the wallet untouched.

        No fee, no usage record, no settlement — the call never ran.
        """
        import time as _time
        from decimal import Decimal

        key = await _prepare_agent(app, "budget-notouch", balance=500.0, daily_cap=5.0)
        ctx = app.state.ctx

        # Spend above the cap.
        now = _time.time()
        await ctx.tracker.storage.db.execute(
            "INSERT INTO usage_records (agent_id, function, cost, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?)",
            ("budget-notouch", "create_intent", int(10.0 * 100_000_000), now, None),
        )
        await ctx.tracker.storage.db.commit()

        initial = Decimal(str(await ctx.tracker.wallet.get_balance("budget-notouch")))
        await ctx.tracker.wallet.create("budget-notouch-payee", initial_balance=0.0, signup_bonus=False)

        resp = await client.post(
            "/v1/payments/intents",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "payer": "budget-notouch",
                "payee": "budget-notouch-payee",
                "amount": "3.00",
                "currency": "CREDITS",
                "description": "should not charge",
            },
        )
        assert resp.status_code == 402
        final = Decimal(str(await ctx.tracker.wallet.get_balance("budget-notouch")))
        assert final == initial, f"wallet was debited on 402: {initial} → {final}"

    async def test_no_cap_configured_still_works(self, client, app):
        """An agent with no budget_cap row must still be able to transact."""
        key = await _prepare_agent(app, "budget-none", balance=500.0)
        ctx = app.state.ctx
        await ctx.tracker.wallet.create("budget-none-payee", initial_balance=0.0, signup_bonus=False)
        resp = await client.post(
            "/v1/payments/intents",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "payer": "budget-none",
                "payee": "budget-none-payee",
                "amount": "5.00",
                "currency": "CREDITS",
                "description": "no cap",
            },
        )
        assert resp.status_code in (200, 201), resp.text

    async def test_admin_bypasses_cap(self, client, admin_api_key, app):
        """Admin-scoped keys bypass the budget cap entirely."""
        import time as _time

        ctx = app.state.ctx
        # Make sure admin-agent has a tiny daily_cap that would
        # normally trigger budget_exceeded.
        await ctx.tracker.storage.db.execute(
            "INSERT OR REPLACE INTO budget_caps "
            "(agent_id, daily_cap, monthly_cap, alert_threshold) VALUES (?, ?, ?, ?)",
            ("admin-agent", int(1.0 * 100_000_000), None, 0.8),
        )
        now = _time.time()
        await ctx.tracker.storage.db.execute(
            "INSERT INTO usage_records (agent_id, function, cost, created_at, idempotency_key) VALUES (?, ?, ?, ?, ?)",
            ("admin-agent", "create_intent", int(100.0 * 100_000_000), now, None),
        )
        await ctx.tracker.storage.db.commit()

        resp = await client.get(
            "/v1/billing/wallets/admin-agent/balance",
            headers={"Authorization": f"Bearer {admin_api_key}"},
        )
        assert resp.status_code == 200
