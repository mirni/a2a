"""Edge case tests for PaywallMiddleware.

Covers: agent_id_param vs api_key_param paths, cost=0, require_balance edge,
revoked keys, and exact rate-limit boundary.
"""

from __future__ import annotations

import time

import pytest

from src.keys import InvalidKeyError, KeyManager
from src.middleware import (
    AuthenticationError,
    InsufficientBalanceError,
    PaywallMiddleware,
    RateLimitError,
    TierInsufficientError,
)
from src.storage import PaywallStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def dummy_tool(agent_id: str, params: dict | None = None) -> dict:
    return {"status": "ok", "agent_id": agent_id}


async def dummy_tool_with_key(api_key: str, params: dict | None = None) -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Tests: agent_id_param vs api_key_param
# ---------------------------------------------------------------------------


class TestGatedAgentIdParam:
    """Call gated function providing agent_id directly (no API key param)."""

    async def test_agent_id_param_with_valid_key(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-edge", tier="free")

        @middleware.gated(tier="free", agent_id_param="agent_id")
        async def my_tool(agent_id: str):
            return {"ok": True, "agent": agent_id}

        result = await my_tool(agent_id="agent-edge")
        assert result == {"ok": True, "agent": "agent-edge"}


class TestGatedApiKeyParam:
    """Call gated function providing API key directly."""

    async def test_api_key_param_resolves_agent(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        created = await key_manager.create_key(agent_id="agent-key", tier="free")

        @middleware.gated(tier="free", api_key_param="api_key")
        async def my_tool(api_key: str):
            return {"status": "ok"}

        result = await my_tool(api_key=created["key"])
        assert result == {"status": "ok"}

    async def test_api_key_param_invalid_key_raises(
        self, middleware: PaywallMiddleware
    ):
        @middleware.gated(tier="free", api_key_param="api_key")
        async def my_tool(api_key: str):
            return {"status": "ok"}

        with pytest.raises(AuthenticationError):
            await my_tool(api_key="a2a_free_this_key_does_not_exist")


# ---------------------------------------------------------------------------
# Tests: cost=0 behavior
# ---------------------------------------------------------------------------


class TestGatedCostZero:
    """gated(cost=0) should not check balance at all."""

    async def test_cost_zero_no_balance_check(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        """With cost=0 on free tier, no wallet is needed."""
        await key_manager.create_key(agent_id="no-wallet-agent", tier="free")

        @middleware.gated(tier="free", cost=0)
        async def free_tool(agent_id: str):
            return {"free": True}

        result = await free_tool(agent_id="no-wallet-agent")
        assert result == {"free": True}


class TestGatedRequireBalanceCostZero:
    """gated(require_balance=True, cost=0) — require_balance is True but cost=0.
    The effective_cost calculation depends on tier_config.cost_per_call.
    For free tier, cost_per_call=0, so effective_cost=0 regardless of declared cost.
    For pro tier, cost_per_call=1, so effective_cost=cost.
    With cost=0 and require_balance=True, effective_cost=0 so balance check is skipped."""

    async def test_require_balance_true_cost_zero_free_tier(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        await key_manager.create_key(agent_id="agent-rb", tier="free")

        @middleware.gated(tier="free", cost=0, require_balance=True)
        async def my_tool(agent_id: str):
            return {"ok": True}

        # Should succeed — effective_cost = 0 because free tier cost_per_call = 0
        result = await my_tool(agent_id="agent-rb")
        assert result == {"ok": True}

    async def test_require_balance_true_cost_zero_pro_tier(
        self, middleware: PaywallMiddleware, key_manager: KeyManager, tracker
    ):
        await key_manager.create_key(agent_id="agent-pro-rb", tier="pro")
        await tracker.wallet.create("agent-pro-rb", initial_balance=0.0)

        @middleware.gated(tier="free", cost=0, require_balance=True)
        async def my_tool(agent_id: str):
            return {"ok": True}

        # Pro tier has cost_per_call=1, but cost=0, so effective_cost=0
        # require_balance && effective_cost > 0 is False, so no check
        result = await my_tool(agent_id="agent-pro-rb")
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Tests: Revoked key
# ---------------------------------------------------------------------------


class TestRevokedKey:
    """Create a key, revoke it, and try to use it via api_key_param."""

    async def test_revoked_key_raises_auth_error_via_api_key_param(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        created = await key_manager.create_key(agent_id="agent-rev", tier="free")
        raw_key = created["key"]
        await key_manager.revoke_key(raw_key)

        @middleware.gated(tier="free", api_key_param="api_key")
        async def my_tool(api_key: str):
            return {"ok": True}

        with pytest.raises(AuthenticationError, match="revoked"):
            await my_tool(api_key=raw_key)

    async def test_revoked_key_via_agent_id_param(
        self, middleware: PaywallMiddleware, key_manager: KeyManager
    ):
        """When using agent_id_param, middleware looks up keys for that agent.
        If all keys are revoked, it should fail with AuthenticationError."""
        created = await key_manager.create_key(agent_id="agent-rev2", tier="free")
        await key_manager.revoke_key(created["key"])

        @middleware.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        with pytest.raises(AuthenticationError, match="No valid API key"):
            await my_tool(agent_id="agent-rev2")


# ---------------------------------------------------------------------------
# Tests: Rate limit at exact boundary
# ---------------------------------------------------------------------------


class TestRateLimitExactBoundary:
    """Make exactly rate_limit_per_hour requests — last should succeed.
    One more should fail."""

    async def test_exact_boundary_succeeds(
        self, tracker, paywall_storage: PaywallStorage, key_manager: KeyManager
    ):
        """Free tier has 100 calls/hour. Seed counter to 99, then call once — should succeed."""
        await key_manager.create_key(agent_id="agent-rl", tier="free")

        mw = PaywallMiddleware(
            tracker=tracker,
            connector="test_edge",
            paywall_storage=paywall_storage,
            key_manager=key_manager,
        )
        mw._initialized = True

        @mw.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        # Seed rate counter to 99 (1 below the limit)
        window_start = time.time()
        for _ in range(99):
            await paywall_storage.increment_rate_count(
                "agent-rl", "hourly_test_edge", window_start
            )

        # 100th call should still succeed
        result = await my_tool(agent_id="agent-rl")
        assert result == {"ok": True}

    async def test_one_past_boundary_fails(
        self, tracker, paywall_storage: PaywallStorage, key_manager: KeyManager
    ):
        """Free tier has 100 calls/hour. Seed counter to 100, then call — should fail."""
        await key_manager.create_key(agent_id="agent-rl2", tier="free")

        mw = PaywallMiddleware(
            tracker=tracker,
            connector="test_edge",
            paywall_storage=paywall_storage,
            key_manager=key_manager,
        )
        mw._initialized = True

        @mw.gated(tier="free")
        async def my_tool(agent_id: str):
            return {"ok": True}

        # Seed rate counter to exactly 100
        window_start = time.time()
        for _ in range(100):
            await paywall_storage.increment_rate_count(
                "agent-rl2", "hourly_test_edge", window_start
            )

        with pytest.raises(RateLimitError):
            await my_tool(agent_id="agent-rl2")
