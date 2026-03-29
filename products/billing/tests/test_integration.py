"""Integration tests: end-to-end billing workflows."""

from __future__ import annotations

import pytest
from src.tracker import UsageTracker
from src.wallet import InsufficientCreditsError


class TestFullWorkflow:
    """Test a complete billing workflow from wallet creation to usage tracking."""

    async def test_full_lifecycle(self, tmp_db):
        async with UsageTracker(storage=tmp_db) as tracker:
            # 1. Create wallet with initial credits
            await tracker.wallet.create("agent-A", initial_balance=1000.0)
            assert await tracker.get_balance("agent-A") == 1000.0

            # 2. Set rate policy
            await tracker.policies.set_policy("agent-A", max_calls_per_min=100, max_spend_per_day=500.0)

            # 3. Register event handler
            events_log = []

            @tracker.events.on_event
            async def log_event(event):
                events_log.append(event)

            # 4. Define metered function
            @tracker.metered(cost=5.0, require_balance=True)
            async def process_document(agent_id, doc):
                return f"processed: {doc}"

            # 5. Call the function
            result = await process_document("agent-A", "hello.pdf")
            assert result == "processed: hello.pdf"

            # 6. Verify balance decreased
            assert await tracker.get_balance("agent-A") == 995.0

            # 7. Verify usage recorded
            usage = await tracker.get_usage("agent-A")
            assert len(usage) == 1
            assert usage[0]["cost"] == 5.0

            # 8. Verify events emitted
            usage_events = [e for e in events_log if e["event_type"] == "usage.recorded"]
            assert len(usage_events) >= 1

            # 9. Verify summary
            summary = await tracker.get_usage_summary("agent-A")
            assert summary["total_calls"] == 1
            assert summary["total_cost"] == 5.0

            # 10. Verify transactions
            txs = await tracker.wallet.get_transactions("agent-A")
            assert len(txs) >= 2  # initial deposit + charge

    async def test_multiple_agents(self, tmp_db):
        async with UsageTracker(storage=tmp_db) as tracker:
            await tracker.wallet.create("agent-A", 100.0)
            await tracker.wallet.create("agent-B", 200.0)

            @tracker.metered(cost=10.0, require_balance=True)
            async def call_api(agent_id):
                return "done"

            await call_api("agent-A")
            await call_api("agent-B")
            await call_api("agent-B")

            assert await tracker.get_balance("agent-A") == 90.0
            assert await tracker.get_balance("agent-B") == 180.0

            summary_a = await tracker.get_usage_summary("agent-A")
            summary_b = await tracker.get_usage_summary("agent-B")
            assert summary_a["total_calls"] == 1
            assert summary_b["total_calls"] == 2

    async def test_wallet_exhaustion(self, tmp_db):
        async with UsageTracker(storage=tmp_db) as tracker:
            await tracker.wallet.create("agent-A", 15.0)

            @tracker.metered(cost=10.0, require_balance=True)
            async def expensive_call(agent_id):
                return "done"

            await expensive_call("agent-A")  # 15 -> 5
            assert await tracker.get_balance("agent-A") == 5.0

            with pytest.raises(InsufficientCreditsError):
                await expensive_call("agent-A")  # 5 < 10

            # Balance unchanged after failed call
            assert await tracker.get_balance("agent-A") == 5.0

    async def test_deposit_and_resume(self, tmp_db):
        async with UsageTracker(storage=tmp_db) as tracker:
            await tracker.wallet.create("agent-A", 5.0)

            @tracker.metered(cost=10.0, require_balance=True)
            async def call(agent_id):
                return "ok"

            with pytest.raises(InsufficientCreditsError):
                await call("agent-A")

            # Top up
            await tracker.wallet.deposit("agent-A", 100.0, "refill")
            assert await tracker.get_balance("agent-A") == 105.0

            # Now it works
            result = await call("agent-A")
            assert result == "ok"
            assert await tracker.get_balance("agent-A") == 95.0

    async def test_event_stream_for_external_billing(self, tmp_db):
        async with UsageTracker(storage=tmp_db) as tracker:
            await tracker.wallet.create("agent-A", 100.0)

            @tracker.metered(cost=1.0, require_balance=True)
            async def call(agent_id):
                return "ok"

            # Make calls without handler (events accumulate as pending)
            await call("agent-A")
            await call("agent-A")

            # External system polls for pending events
            pending = await tracker.events.get_pending()
            assert len(pending) >= 2

            # Acknowledge them
            for event in pending:
                await tracker.events.acknowledge(event["id"])

            # No more pending
            pending = await tracker.events.get_pending()
            assert len(pending) == 0
