"""Tests targeting specific uncovered lines in paywall/ to raise coverage to 95%+.

Focus areas:
- middleware.py: InsufficientBalanceError exception, MISSING_AGENT_ID path,
  require_balance with insufficient funds, billing charge failure branch.
- storage.py: sliding-window rate event helpers, cleanup, null-scopes default.
- keys.py: tier-as-TierName input, 90-day key age warning.
- scoping.py: check_all aggregate validator.
- tiers.py: valid-enum-but-missing-config ValueError.
"""

from __future__ import annotations

import time

import pytest
from src.middleware import (
    InsufficientBalanceError,
    PaywallError,
)
from src.scoping import KeyScopeError, ScopeChecker
from src.storage import PaywallStorage

# ---------------------------------------------------------------------------
# InsufficientBalanceError — middleware.py lines 84-91
# ---------------------------------------------------------------------------


class TestInsufficientBalanceError:
    def test_exception_message_and_attrs(self):
        err = InsufficientBalanceError(agent_id="agent-x", required=50.0, available=10.0)
        assert err.required == 50.0
        assert err.available == 10.0
        assert err.error_code == "INSUFFICIENT_BALANCE"
        assert err.agent_id == "agent-x"
        assert "10" in str(err) and "50" in str(err)


# ---------------------------------------------------------------------------
# Middleware: MISSING_AGENT_ID path (line 187)
# ---------------------------------------------------------------------------


class TestMissingAgentId:
    async def test_no_agent_id_raises_paywall_error(self, middleware):
        @middleware.gated(tier="free", agent_id_param="agent_id")
        async def my_tool(**kwargs):
            return {"ok": True}

        with pytest.raises(PaywallError) as exc_info:
            await my_tool()  # no args, no kwargs[agent_id_param]
        assert exc_info.value.error_code == "MISSING_AGENT_ID"


# ---------------------------------------------------------------------------
# Middleware: require_balance path — insufficient + charge failure
# (lines 245-259 + 273-299)
# ---------------------------------------------------------------------------


def _patch_tier_cost(monkeypatch, tier_name: str, new_cost: float) -> None:
    """Patch a tier's cost_per_call to a positive value so the balance check
    path in middleware actually runs."""
    from src import middleware as mw_mod

    original_get_tier_config = mw_mod.get_tier_config

    def patched(tier):
        cfg = original_get_tier_config(tier)
        # Return a copy with overridden cost_per_call for the target tier
        if (hasattr(tier, "value") and tier.value == tier_name) or tier == tier_name:
            from dataclasses import replace

            return replace(cfg, cost_per_call=new_cost)
        return cfg

    monkeypatch.setattr(mw_mod, "get_tier_config", patched)


class TestBalanceCheckAndChargeFailure:
    async def test_insufficient_balance_raises_and_audits(self, middleware, key_manager, monkeypatch):
        _patch_tier_cost(monkeypatch, "pro", 5.0)
        await key_manager.create_key(agent_id="broke-agent", tier="pro")

        @middleware.gated(tier="pro", cost=5.0, agent_id_param="agent_id")
        async def paid_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(InsufficientBalanceError):
            await paid_tool(agent_id="broke-agent")

    async def test_charge_failure_logs_but_does_not_block(self, middleware, key_manager, tracker, monkeypatch, caplog):
        """When wallet.charge raises, the tool result is still returned and the
        failure is logged + audited (lines 284-307)."""
        import logging

        _patch_tier_cost(monkeypatch, "pro", 2.0)
        await key_manager.create_key(agent_id="funded-agent", tier="pro")

        # Fund the wallet enough to pass the balance check
        monkeypatch.setattr(tracker, "get_balance", _async_return(1000.0))

        # Make charge fail
        async def failing_charge(*args, **kwargs):
            raise RuntimeError("stripe down")

        monkeypatch.setattr(tracker.wallet, "charge", failing_charge)

        @middleware.gated(tier="pro", cost=2.0, agent_id_param="agent_id")
        async def paid_tool(agent_id: str):
            return {"ok": True, "data": "result"}

        with caplog.at_level(logging.WARNING):
            result = await paid_tool(agent_id="funded-agent")
        assert result == {"ok": True, "data": "result"}
        assert any("Charge failed" in r.message for r in caplog.records)

    async def test_get_balance_exception_treated_as_zero_balance(self, middleware, key_manager, tracker, monkeypatch):
        """When tracker.get_balance raises, balance is treated as 0.0 and
        InsufficientBalanceError is raised for any non-zero cost."""
        _patch_tier_cost(monkeypatch, "pro", 1.0)
        await key_manager.create_key(agent_id="flaky-agent", tier="pro")

        async def raising_get_balance(*args, **kwargs):
            raise RuntimeError("db timeout")

        monkeypatch.setattr(tracker, "get_balance", raising_get_balance)

        @middleware.gated(tier="pro", cost=1.0, agent_id_param="agent_id")
        async def paid_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(InsufficientBalanceError):
            await paid_tool(agent_id="flaky-agent")


def _async_return(value):
    async def _f(*args, **kwargs):
        return value

    return _f


# ---------------------------------------------------------------------------
# PaywallStorage: sliding-window rate-event helpers
# (lines 291-333)
# ---------------------------------------------------------------------------


class TestSlidingWindowRateHelpers:
    async def test_record_and_count_sliding_window(self, paywall_storage):
        await paywall_storage.record_rate_event("agent-rate", "hourly_connector", tool_name="some_tool")
        await paywall_storage.record_rate_event("agent-rate", "hourly_connector", tool_name="another_tool")
        count = await paywall_storage.get_sliding_window_count("agent-rate", "hourly_connector", window_seconds=3600.0)
        assert count == 2

    async def test_get_tool_rate_count_filters_by_tool(self, paywall_storage):
        await paywall_storage.record_rate_event("agent-r2", "k", tool_name="tool_a")
        await paywall_storage.record_rate_event("agent-r2", "k", tool_name="tool_b")
        await paywall_storage.record_rate_event("agent-r2", "k", tool_name="tool_a")
        assert await paywall_storage.get_tool_rate_count("agent-r2", "tool_a") == 2
        assert await paywall_storage.get_tool_rate_count("agent-r2", "tool_b") == 1
        assert await paywall_storage.get_tool_rate_count("agent-r2", "tool_missing") == 0

    async def test_get_burst_count(self, paywall_storage):
        await paywall_storage.record_rate_event("agent-burst", "k", tool_name="t")
        await paywall_storage.record_rate_event("agent-burst", "k", tool_name="t")
        burst = await paywall_storage.get_burst_count("agent-burst", "k", burst_window_seconds=60.0)
        assert burst == 2

    async def test_cleanup_old_rate_events(self, paywall_storage):
        # Insert an ancient event
        import time as _time

        old_ts = _time.time() - 10_000  # 10000s ago
        await paywall_storage.db.execute(
            "INSERT INTO rate_events (agent_id, window_key, tool_name, timestamp) VALUES (?, ?, ?, ?)",
            ("agent-old", "k", "t", old_ts),
        )
        await paywall_storage.db.commit()

        deleted = await paywall_storage.cleanup_old_rate_events(max_age_seconds=3600.0)
        assert deleted == 1

    async def test_get_sliding_window_count_empty(self, paywall_storage):
        """No events returns 0 (exercises the `row[0] if row else 0` fallback)."""
        assert await paywall_storage.get_sliding_window_count("never", "never", 3600.0) == 0
        assert await paywall_storage.get_tool_rate_count("never", "no-tool") == 0
        assert await paywall_storage.get_burst_count("never", "never") == 0


# ---------------------------------------------------------------------------
# PaywallStorage: null-scopes fallback in _deserialize_key_row (line 201)
# ---------------------------------------------------------------------------


class TestKeyRowDeserialization:
    def test_scopes_null_column_defaults_to_read_write(self):
        """If a row's scopes column is NULL, deserialization backfills it to
        ["read", "write"] (defensive path — production schema forbids NULL)."""
        result = PaywallStorage._deserialize_key_row(
            {
                "key_hash": "h",
                "agent_id": "a",
                "tier": "free",
                "scopes": None,
                "allowed_tools": None,
                "allowed_agent_ids": None,
            }
        )
        assert result["scopes"] == ["read", "write"]


# ---------------------------------------------------------------------------
# KeyManager: TierName enum input + 90-day age warning
# ---------------------------------------------------------------------------


class TestKeyManagerExtras:
    async def test_create_key_accepts_tier_enum(self, key_manager):
        from src.tiers import TierName

        result = await key_manager.create_key(agent_id="agent-enum", tier=TierName.STARTER)
        assert result["tier"] == "starter"

    async def test_validate_key_flags_old_keys(self, key_manager, paywall_storage):
        """Keys created > 90 days ago should get a _key_age_warning annotation."""
        created = await key_manager.create_key(agent_id="agent-old-key", tier="free")
        key_hash = created["key_hash"]

        # Backdate the created_at to 100 days ago
        old_ts = time.time() - (100 * 86400)
        await paywall_storage.db.execute(
            "UPDATE api_keys SET created_at = ? WHERE key_hash = ?",
            (old_ts, key_hash),
        )
        await paywall_storage.db.commit()

        record = await key_manager.validate_key(created["key"])
        assert "_key_age_warning" in record
        assert "days old" in record["_key_age_warning"]


# ---------------------------------------------------------------------------
# Scoping: check_all aggregator (lines 155-160)
# ---------------------------------------------------------------------------


class TestScopingCheckAll:
    def test_check_all_passes_when_everything_allowed(self):
        scope = ScopeChecker(
            scopes=["read", "write", "admin"],
            allowed_tools=["ping", "search"],
            allowed_agent_ids=["agent-1", "agent-2"],
        )
        # Should not raise
        scope.check_all(tool_name="ping", agent_id="agent-1")

    def test_check_all_rejects_disallowed_tool(self):
        scope = ScopeChecker(
            scopes=["read", "write"],
            allowed_tools=["ping"],
            allowed_agent_ids=None,
        )
        with pytest.raises(KeyScopeError, match="not in allowed tools"):
            scope.check_all(tool_name="not_allowed", agent_id="agent-1")

    def test_check_all_rejects_disallowed_agent(self):
        scope = ScopeChecker(
            scopes=["read", "write", "admin"],
            allowed_tools=None,
            allowed_agent_ids=["agent-1"],
        )
        with pytest.raises(KeyScopeError, match="not in allowed agent_ids"):
            scope.check_all(tool_name="ping", agent_id="agent-2")

    def test_check_all_skips_agent_check_when_none(self):
        scope = ScopeChecker(
            scopes=["read", "write", "admin"],
            allowed_tools=None,
            allowed_agent_ids=None,
        )
        # agent_id=None => skip agent check entirely
        scope.check_all(tool_name="ping", agent_id=None)


# ---------------------------------------------------------------------------
# Tiers: valid enum but no config in TIER_CONFIGS (line 73)
# ---------------------------------------------------------------------------


class TestTierConfigMissing:
    def test_unknown_tier_string_raises(self):
        from src.tiers import get_tier_config

        with pytest.raises(ValueError, match="Unknown tier"):
            get_tier_config("platinum_plus")

    def test_valid_enum_but_no_config(self, monkeypatch):
        """If TIER_CONFIGS is missing an entry for a valid TierName, raise."""
        from src import tiers

        original = tiers.TIER_CONFIGS
        # Remove a valid enum from the config dict
        patched = {k: v for k, v in original.items() if k != tiers.TierName.FREE}
        monkeypatch.setattr(tiers, "TIER_CONFIGS", patched)
        with pytest.raises(ValueError, match="No configuration for tier"):
            tiers.get_tier_config(tiers.TierName.FREE)
