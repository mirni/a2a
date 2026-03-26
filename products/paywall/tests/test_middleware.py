"""Tests for PaywallMiddleware: auth, tier, rate limit, wallet checks."""

from __future__ import annotations

import pytest

from src.keys import KeyManager
from src.middleware import (
    AuthenticationError,
    InsufficientBalanceError,
    PaywallMiddleware,
    RateLimitError,
    TierInsufficientError,
)
from src.storage import PaywallStorage


# ---------------------------------------------------------------------------
# Helper: a simple async tool function
# ---------------------------------------------------------------------------


async def dummy_tool(agent_id: str, params: dict | None = None) -> dict:
    """A simple tool that returns a success response."""
    return {"status": "ok", "agent_id": agent_id}


async def dummy_tool_with_key(api_key: str, params: dict | None = None) -> dict:
    """A simple tool that takes an API key."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMiddlewareInitialization:
    async def test_uninitialized_raises(self, tracker):
        mw = PaywallMiddleware(tracker=tracker, connector="test")

        @mw.gated()
        async def my_tool(agent_id: str):
            return "ok"

        with pytest.raises(RuntimeError, match="not initialized"):
            await my_tool(agent_id="agent-1")

    async def test_initialize_creates_storage(self, tracker):
        mw = PaywallMiddleware(tracker=tracker, connector="test")
        await mw.initialize()
        assert mw.paywall_storage is not None
        assert mw.key_manager is not None
        assert mw._initialized is True
        await mw.close()

    async def test_double_initialize_is_safe(self, tracker):
        mw = PaywallMiddleware(tracker=tracker, connector="test")
        await mw.initialize()
        await mw.initialize()  # Should not raise
        await mw.close()


class TestAuthenticationCheck:
    async def test_valid_agent_with_key(self, middleware: PaywallMiddleware, key_manager: KeyManager):
        created = await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        result = await my_tool(agent_id="agent-1")
        assert result == {"ok": True}

    async def test_no_key_raises_auth_error(self, middleware: PaywallMiddleware):
        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(AuthenticationError, match="No valid API key"):
            await my_tool(agent_id="unknown-agent")

    async def test_revoked_key_agent_fails(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        created = await key_manager.create_key(agent_id="agent-1", tier="free")
        await key_manager.revoke_key(created["key"])

        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(AuthenticationError, match="No valid API key"):
            await my_tool(agent_id="agent-1")

    async def test_api_key_param_mode(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        created = await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free", api_key_param="api_key")
        async def my_tool(api_key: str, params: dict | None = None):
            return {"ok": True}

        result = await my_tool(api_key=created["key"])
        assert result == {"ok": True}

    async def test_invalid_api_key_param_raises(self, middleware: PaywallMiddleware):
        @middleware.gated(tier="free", api_key_param="api_key")
        async def my_tool(api_key: str):
            return {"ok": True}

        with pytest.raises(AuthenticationError):
            await my_tool(api_key="a2a_pro_invalid_key_here1234")


class TestTierEnforcement:
    async def test_matching_tier_allowed(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-1", tier="pro")

        @middleware.gated(tier="pro")
        async def pro_tool(agent_id: str):
            return {"tier": "pro"}

        result = await pro_tool(agent_id="agent-1")
        assert result == {"tier": "pro"}

    async def test_higher_tier_allowed(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-1", tier="enterprise")

        @middleware.gated(tier="pro")
        async def pro_tool(agent_id: str):
            return {"tier": "pro"}

        result = await pro_tool(agent_id="agent-1")
        assert result == {"tier": "pro"}

    async def test_lower_tier_rejected(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="pro")
        async def pro_tool(agent_id: str):
            return {"tier": "pro"}

        with pytest.raises(TierInsufficientError, match="insufficient"):
            await pro_tool(agent_id="agent-1")

    async def test_tier_error_contains_details(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="enterprise")
        async def enterprise_tool(agent_id: str):
            return {}

        with pytest.raises(TierInsufficientError) as exc_info:
            await enterprise_tool(agent_id="agent-1")

        err = exc_info.value
        assert err.agent_tier == "free"
        assert err.required_tier == "enterprise"
        assert err.error_code == "TIER_INSUFFICIENT"


class TestRateLimiting:
    async def test_within_rate_limit(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        # Free tier: 100 calls/hour. Make a few calls.
        for _ in range(5):
            result = await my_tool(agent_id="agent-1")
            assert result == {"ok": True}

    async def test_exceeds_rate_limit(
        self,
        tracker,
        paywall_storage: PaywallStorage,
        key_manager: KeyManager,
    ):
        """Use a custom middleware that simulates reaching the rate limit."""
        # Create a free tier agent (100 calls/hour limit)
        await key_manager.create_key(agent_id="agent-1", tier="free")

        mw = PaywallMiddleware(
            tracker=tracker,
            connector="test",
            paywall_storage=paywall_storage,
            key_manager=key_manager,
        )
        mw._initialized = True

        @mw.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        # Manually set rate counter to the limit.
        # Use current time as window_start so it won't be considered expired
        # when the middleware checks (middleware uses now - 3600 as threshold).
        import time

        window_start = time.time()
        for _ in range(100):
            await paywall_storage.increment_rate_count(
                "agent-1", "hourly_test", window_start
            )

        with pytest.raises(RateLimitError, match="rate limit exceeded"):
            await my_tool(agent_id="agent-1")

    async def test_rate_limit_error_details(
        self,
        tracker,
        paywall_storage: PaywallStorage,
        key_manager: KeyManager,
    ):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        mw = PaywallMiddleware(
            tracker=tracker,
            connector="test",
            paywall_storage=paywall_storage,
            key_manager=key_manager,
        )
        mw._initialized = True

        @mw.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        import time

        window_start = time.time()
        for _ in range(100):
            await paywall_storage.increment_rate_count(
                "agent-1", "hourly_test", window_start
            )

        with pytest.raises(RateLimitError) as exc_info:
            await my_tool(agent_id="agent-1")

        err = exc_info.value
        assert err.limit == 100
        assert err.error_code == "RATE_LIMIT_EXCEEDED"


class TestWalletCheck:
    async def test_free_tier_no_wallet_check(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        """Free tier with cost=0 should not check wallet."""
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free", cost=0)
        async def free_tool(agent_id: str):
            return {"ok": True}

        result = await free_tool(agent_id="agent-1")
        assert result == {"ok": True}

    async def test_pro_tier_insufficient_balance(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, tracker
    ):
        """Pro tier with cost should fail if wallet is empty."""
        await key_manager.create_key(agent_id="agent-1", tier="pro")
        # Create wallet with 0 balance
        await tracker.wallet.create("agent-1", initial_balance=0.0)

        @middleware.gated(tier="free", cost=1)
        async def paid_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(InsufficientBalanceError, match="insufficient balance"):
            await paid_tool(agent_id="agent-1")

    async def test_pro_tier_sufficient_balance(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, tracker
    ):
        """Pro tier with cost should succeed if wallet has balance."""
        await key_manager.create_key(agent_id="agent-1", tier="pro")
        await tracker.wallet.create("agent-1", initial_balance=100.0)

        @middleware.gated(tier="free", cost=1)
        async def paid_tool(agent_id: str):
            return {"ok": True}

        result = await paid_tool(agent_id="agent-1")
        assert result == {"ok": True}

    async def test_wallet_charged_after_call(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, tracker
    ):
        """After successful call, wallet should be charged."""
        await key_manager.create_key(agent_id="agent-1", tier="pro")
        await tracker.wallet.create("agent-1", initial_balance=100.0)

        @middleware.gated(tier="free", cost=5)
        async def paid_tool(agent_id: str):
            return {"ok": True}

        await paid_tool(agent_id="agent-1")
        balance = await tracker.get_balance("agent-1")
        assert balance == 95.0

    async def test_free_tier_cost_zero_even_if_declared(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        """Free tier should not charge even if cost is declared (cost_per_call=0)."""
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free", cost=5)
        async def tool(agent_id: str):
            return {"ok": True}

        # Should succeed without wallet because free tier cost_per_call=0
        result = await tool(agent_id="agent-1")
        assert result == {"ok": True}


class TestAuditLogging:
    async def test_successful_call_logged(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, paywall_storage
    ):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        await my_tool(agent_id="agent-1")

        logs = await paywall_storage.get_audit_log("agent-1")
        assert len(logs) == 1
        assert logs[0]["allowed"] == 1
        assert logs[0]["connector"] == "test_connector"

    async def test_denied_call_logged(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, paywall_storage
    ):
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="pro")
        async def pro_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(TierInsufficientError):
            await pro_tool(agent_id="agent-1")

        logs = await paywall_storage.get_audit_log("agent-1")
        assert len(logs) == 1
        assert logs[0]["allowed"] == 0
        assert "insufficient" in logs[0]["reason"].lower()

    async def test_auth_failure_logged(self, middleware: PaywallMiddleware, paywall_storage):
        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(AuthenticationError):
            await my_tool(agent_id="unknown-agent")

        logs = await paywall_storage.get_audit_log("unknown-agent")
        assert len(logs) == 1
        assert logs[0]["allowed"] == 0


class TestUsageMetering:
    async def test_usage_recorded_in_billing(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, tracker
    ):
        """Pro tier calls should be recorded in the billing layer."""
        await key_manager.create_key(agent_id="agent-1", tier="pro")
        await tracker.wallet.create("agent-1", initial_balance=100.0)

        @middleware.gated(tier="free", cost=1)
        async def paid_tool(agent_id: str):
            return {"ok": True}

        await paid_tool(agent_id="agent-1")

        usage = await tracker.get_usage("agent-1")
        assert len(usage) == 1
        assert usage[0]["cost"] == 1.0
        assert usage[0]["metadata"]["connector"] == "test_connector"

    async def test_free_tier_no_usage_recorded(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, tracker
    ):
        """Free tier calls (cost=0) should not be recorded in billing."""
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free", cost=0)
        async def free_tool(agent_id: str):
            return {"ok": True}

        await free_tool(agent_id="agent-1")

        usage = await tracker.get_usage("agent-1")
        assert len(usage) == 0


class TestEdgeCases:
    async def test_agent_id_from_positional_arg(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        """agent_id extracted from first positional argument."""
        await key_manager.create_key(agent_id="agent-1", tier="free")

        @middleware.gated(tier="free")
        async def my_tool(agent_id: str, data: str = ""):
            return {"agent_id": agent_id}

        result = await my_tool("agent-1")
        assert result == {"agent_id": "agent-1"}

    async def test_multiple_keys_uses_first_active(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        """If agent has multiple keys, use the most recent active one."""
        created1 = await key_manager.create_key(agent_id="agent-1", tier="free")
        created2 = await key_manager.create_key(agent_id="agent-1", tier="pro")

        @middleware.gated(tier="pro")
        async def pro_tool(agent_id: str):
            return {"ok": True}

        # Should work because agent has a pro key
        result = await pro_tool(agent_id="agent-1")
        assert result == {"ok": True}
