"""PaywallMiddleware: decorator that intercepts MCP tool calls for auth, tier, rate limit, and billing.

Usage::

    from a2a_billing import UsageTracker
    from a2a_paywall import PaywallMiddleware

    tracker = UsageTracker(storage="sqlite:///billing.db")
    middleware = PaywallMiddleware(tracker=tracker, connector="stripe")

    @middleware.gated(tier="free", cost=1)
    async def my_tool(agent_id: str, params: dict):
        ...
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

logger = logging.getLogger("a2a.paywall")

from .keys import InvalidKeyError, KeyManager
from .storage import PaywallStorage
from .tiers import get_tier_config, tier_has_access

P = ParamSpec("P")
T = TypeVar("T")


class PaywallError(Exception):
    """Base class for paywall errors."""

    def __init__(self, message: str, error_code: str, agent_id: str = "") -> None:
        self.error_code = error_code
        self.agent_id = agent_id
        super().__init__(message)


class PaywallAuthError(PaywallError):
    """Raised when API key validation fails."""

    def __init__(self, agent_id: str, reason: str = "Invalid API key") -> None:
        super().__init__(
            f"Authentication failed for agent {agent_id}: {reason}",
            error_code="AUTH_FAILED",
            agent_id=agent_id,
        )


class TierInsufficientError(PaywallError):
    """Raised when agent tier is too low for the requested operation."""

    def __init__(self, agent_id: str, agent_tier: str, required_tier: str) -> None:
        self.agent_tier = agent_tier
        self.required_tier = required_tier
        super().__init__(
            f"Agent {agent_id}: tier '{agent_tier}' insufficient, requires '{required_tier}'",
            error_code="TIER_INSUFFICIENT",
            agent_id=agent_id,
        )


class RateLimitError(PaywallError):
    """Raised when agent exceeds tier rate limit."""

    def __init__(self, agent_id: str, current: int, limit: int) -> None:
        self.current = current
        self.limit = limit
        super().__init__(
            f"Agent {agent_id}: rate limit exceeded ({current}/{limit} calls/hour)",
            error_code="RATE_LIMIT_EXCEEDED",
            agent_id=agent_id,
        )


class InsufficientBalanceError(PaywallError):
    """Raised when agent wallet has insufficient balance."""

    def __init__(self, agent_id: str, required: float, available: float) -> None:
        self.required = required
        self.available = available
        super().__init__(
            f"Agent {agent_id}: insufficient balance ({available} available, {required} required)",
            error_code="INSUFFICIENT_BALANCE",
            agent_id=agent_id,
        )


@dataclass
class PaywallMiddleware:
    """Middleware that gates MCP tool calls behind auth, tier checks, rate limits, and billing.

    Args:
        tracker: A connected UsageTracker instance from the billing layer.
        connector: Name of the connector this middleware protects (e.g. "stripe").
        paywall_storage: PaywallStorage instance. If None, one is created using :memory:.
        key_manager: KeyManager instance. If None, one is created from paywall_storage.
    """

    tracker: Any  # UsageTracker
    connector: str
    paywall_storage: PaywallStorage | None = None
    key_manager: KeyManager | None = None
    _initialized: bool = field(default=False, init=False, repr=False)

    async def initialize(self, paywall_dsn: str = "sqlite:///:memory:") -> None:
        """Initialize storage and key manager if not provided externally."""
        if self._initialized:
            return
        if self.paywall_storage is None:
            self.paywall_storage = PaywallStorage(dsn=paywall_dsn)
            await self.paywall_storage.connect()
        if self.key_manager is None:
            self.key_manager = KeyManager(storage=self.paywall_storage)
        self._initialized = True

    async def close(self) -> None:
        """Close underlying storage connections."""
        if self.paywall_storage is not None:
            await self.paywall_storage.close()

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("PaywallMiddleware not initialized. Call await middleware.initialize() first.")

    def gated(
        self,
        tier: str = "free",
        cost: float = 0.0,
        require_balance: bool | None = None,
        agent_id_param: str = "agent_id",
        api_key_param: str | None = None,
    ) -> Callable:
        """Decorator that gates an async function behind paywall checks.

        Args:
            tier: Minimum tier required to call this function.
            cost: Credit cost per call.
            require_balance: If True, check wallet balance. Defaults to True if cost > 0.
            agent_id_param: Name of the kwarg holding the agent_id.
            api_key_param: If set, look up agent_id from this API key param instead.
        """
        if require_balance is None:
            require_balance = cost > 0

        def decorator(fn: Callable[P, Any]) -> Callable[P, Any]:
            @functools.wraps(fn)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                self._ensure_initialized()
                assert self.paywall_storage is not None
                assert self.key_manager is not None

                # Step 1: Extract agent_id (from key or param)
                agent_id: str | None = None
                agent_tier: str | None = None

                if api_key_param and api_key_param in kwargs:
                    # Validate API key and extract agent_id + tier
                    raw_key = kwargs[api_key_param]
                    try:
                        record = await self.key_manager.validate_key(str(raw_key))
                    except InvalidKeyError as e:
                        agent_id = str(raw_key)[:20]  # partial for error logging
                        await self.paywall_storage.record_audit(
                            agent_id=agent_id,
                            connector=self.connector,
                            function=fn.__qualname__,
                            tier="",
                            cost=cost,
                            allowed=False,
                            reason=e.reason,
                        )
                        raise PaywallAuthError(agent_id, e.reason) from e
                    agent_id = record["agent_id"]
                    agent_tier = record["tier"]
                else:
                    # Extract from param
                    agent_id = str(kwargs.get(agent_id_param)) if agent_id_param in kwargs else None
                    if agent_id is None and args:
                        agent_id = str(args[0])
                    if agent_id is None:
                        raise PaywallError(
                            "Cannot determine agent_id",
                            error_code="MISSING_AGENT_ID",
                        )
                    agent_id = str(agent_id)

                    # Look up tier from stored keys
                    keys = await self.paywall_storage.get_keys_for_agent(agent_id)
                    active_keys = [k for k in keys if not k["revoked"]]
                    agent_tier = active_keys[0]["tier"] if active_keys else None

                if agent_tier is None:
                    await self.paywall_storage.record_audit(
                        agent_id=agent_id,
                        connector=self.connector,
                        function=fn.__qualname__,
                        tier="",
                        cost=cost,
                        allowed=False,
                        reason="No valid API key found",
                    )
                    raise PaywallAuthError(agent_id, "No valid API key found")

                # Step 2: Check tier access
                if not tier_has_access(agent_tier, tier):
                    await self.paywall_storage.record_audit(
                        agent_id=agent_id,
                        connector=self.connector,
                        function=fn.__qualname__,
                        tier=agent_tier,
                        cost=cost,
                        allowed=False,
                        reason=f"Tier '{agent_tier}' insufficient, requires '{tier}'",
                    )
                    raise TierInsufficientError(agent_id, agent_tier, tier)

                # Step 3: Check rate limit (hourly window)
                tier_config = get_tier_config(agent_tier)
                window_key = f"hourly_{self.connector}"
                now = time.time()
                window_start = now - 3600  # 1 hour sliding window

                current_count = await self.paywall_storage.get_rate_count(agent_id, window_key, window_start)
                if current_count >= tier_config.rate_limit_per_hour:
                    await self.paywall_storage.record_audit(
                        agent_id=agent_id,
                        connector=self.connector,
                        function=fn.__qualname__,
                        tier=agent_tier,
                        cost=cost,
                        allowed=False,
                        reason=f"Rate limit exceeded: {current_count}/{tier_config.rate_limit_per_hour}",
                    )
                    raise RateLimitError(agent_id, current_count, tier_config.rate_limit_per_hour)

                # Step 4: Check wallet balance (if tier requires payment)
                effective_cost = cost if tier_config.cost_per_call > 0 else 0.0
                if require_balance and effective_cost > 0:
                    try:
                        balance = await self.tracker.get_balance(agent_id)
                    except Exception:
                        balance = 0.0
                    if balance < effective_cost:
                        await self.paywall_storage.record_audit(
                            agent_id=agent_id,
                            connector=self.connector,
                            function=fn.__qualname__,
                            tier=agent_tier,
                            cost=effective_cost,
                            allowed=False,
                            reason=f"Insufficient balance: {balance} < {effective_cost}",
                        )
                        raise InsufficientBalanceError(agent_id, effective_cost, balance)

                # -- All checks passed, execute the function --

                # Increment rate counter
                await self.paywall_storage.increment_rate_count(agent_id, window_key, window_start)

                # Execute
                start = time.time()
                result = await fn(*args, **kwargs)
                elapsed = time.time() - start

                # Step 5: Meter usage via tracker
                if effective_cost > 0:
                    await self.tracker._storage.record_usage(
                        agent_id=agent_id,
                        function=fn.__qualname__,
                        cost=effective_cost,
                        tokens=0,
                        metadata={
                            "connector": self.connector,
                            "elapsed_ms": round(elapsed * 1000, 2),
                        },
                    )
                    # Charge wallet
                    try:
                        await self.tracker.wallet.charge(
                            agent_id,
                            effective_cost,
                            description=f"paywall:{self.connector}:{fn.__qualname__}",
                        )
                    except Exception as charge_err:
                        # Charge failure should not block response, but must be logged
                        logger.warning(
                            "Charge failed for agent %s on %s:%s — %s",
                            agent_id,
                            self.connector,
                            fn.__qualname__,
                            charge_err,
                        )
                        await self.paywall_storage.record_audit(
                            agent_id=agent_id,
                            connector=self.connector,
                            function=fn.__qualname__,
                            tier=agent_tier,
                            cost=effective_cost,
                            allowed=True,
                            reason=f"charge_failed: {charge_err}",
                        )

                # Step 6: Record audit log
                await self.paywall_storage.record_audit(
                    agent_id=agent_id,
                    connector=self.connector,
                    function=fn.__qualname__,
                    tier=agent_tier,
                    cost=effective_cost,
                    allowed=True,
                )

                return result

            return wrapper

        return decorator
