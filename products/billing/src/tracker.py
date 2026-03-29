"""UsageTracker: middleware that counts calls, tokens, and custom metrics per agent.

Provides the `metered` decorator and `require_credits` decorator for metering function calls.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

from .events import BillingEventStream
from .policies import RatePolicyManager
from .storage import StorageBackend
from .wallet import InsufficientCreditsError, Wallet, WalletNotFoundError

P = ParamSpec("P")
T = TypeVar("T")


@dataclass
class UsageTracker:
    """Main entry point for the billing layer.

    Wraps storage, wallet, policies, and events into a single cohesive interface.

    Usage::

        tracker = UsageTracker(storage="sqlite:///billing.db")
        await tracker.connect()

        @tracker.metered(cost=1)
        async def my_tool(params):
            ...
    """

    storage_dsn: str
    _storage: StorageBackend = field(init=False, repr=False)
    _wallet: Wallet = field(init=False, repr=False)
    _policies: RatePolicyManager = field(init=False, repr=False)
    _events: BillingEventStream = field(init=False, repr=False)

    def __init__(self, storage: str) -> None:
        self.storage_dsn = storage
        self._storage = StorageBackend(dsn=storage)
        self._wallet = Wallet(storage=self._storage)
        self._policies = RatePolicyManager(storage=self._storage)
        self._events = BillingEventStream(storage=self._storage)

    async def connect(self, *, apply_migrations: bool = False) -> None:
        """Open the database and ensure schema exists."""
        await self._storage.connect(apply_migrations=apply_migrations)

    async def close(self) -> None:
        """Close the database connection."""
        await self._storage.close()

    async def __aenter__(self) -> UsageTracker:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # -----------------------------------------------------------------------
    # Accessors for sub-components
    # -----------------------------------------------------------------------

    @property
    def wallet(self) -> Wallet:
        return self._wallet

    @property
    def policies(self) -> RatePolicyManager:
        return self._policies

    @property
    def events(self) -> BillingEventStream:
        return self._events

    @property
    def storage(self) -> StorageBackend:
        return self._storage

    # -----------------------------------------------------------------------
    # Metered decorator
    # -----------------------------------------------------------------------

    def metered(
        self,
        cost: float = 1.0,
        agent_id_param: str = "agent_id",
        tokens_param: str | None = None,
        require_balance: bool = False,
    ) -> Callable:
        """Decorator that meters an async function call.

        Args:
            cost: Credit cost per call.
            agent_id_param: Name of the kwarg or first positional arg holding the agent_id.
            tokens_param: Optional kwarg name to extract token count from.
            require_balance: If True, check wallet balance before executing and charge after.
        """

        def decorator(fn: Callable[P, Any]) -> Callable[P, Any]:
            @functools.wraps(fn)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                # Extract agent_id
                agent_id = kwargs.get(agent_id_param)
                if agent_id is None and args:
                    agent_id = args[0]
                if agent_id is None:
                    raise ValueError(
                        f"Cannot determine agent_id: expected kwarg '{agent_id_param}' or first positional arg"
                    )

                # Extract tokens if configured
                tokens = 0
                if tokens_param and tokens_param in kwargs:
                    tokens = int(str(kwargs[tokens_param]))

                # Policy checks
                await self._policies.check_all(str(agent_id), cost)

                # Balance check
                if require_balance:
                    try:
                        balance = await self._wallet.get_balance(str(agent_id))
                    except WalletNotFoundError:
                        raise InsufficientCreditsError(str(agent_id), cost, 0.0) from None
                    if balance < cost:
                        raise InsufficientCreditsError(str(agent_id), cost, balance)

                # Execute the function
                start = time.time()
                result = await fn(*args, **kwargs)
                elapsed = time.time() - start

                # Record usage
                func_name = fn.__qualname__
                await self._storage.record_usage(
                    agent_id=str(agent_id),
                    function=func_name,
                    cost=cost,
                    tokens=tokens,
                    metadata={"elapsed_ms": round(elapsed * 1000, 2)},
                )

                # Charge wallet if required
                if require_balance:
                    await self._wallet.charge(str(agent_id), cost, description=f"metered:{func_name}")

                # Emit usage event
                await self._events.emit(
                    "usage.recorded",
                    str(agent_id),
                    {
                        "function": func_name,
                        "cost": cost,
                        "tokens": tokens,
                        "elapsed_ms": round(elapsed * 1000, 2),
                    },
                )

                return result

            return wrapper

        return decorator

    # -----------------------------------------------------------------------
    # Usage API
    # -----------------------------------------------------------------------

    async def get_usage(
        self,
        agent_id: str,
        since: float | None = None,
        until: float | None = None,
        limit: int = 1000,
        function: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query usage history for an agent, optionally filtered by function name."""
        return await self._storage.get_usage(agent_id, since, until, limit, function=function)

    async def get_usage_summary(self, agent_id: str, since: float | None = None) -> dict[str, Any]:
        """Get aggregated usage summary for an agent."""
        return await self._storage.get_usage_summary(agent_id, since)

    async def get_balance(self, agent_id: str) -> float:
        """Get current balance for an agent."""
        return await self._wallet.get_balance(agent_id)

    async def get_projected_cost(self, agent_id: str, hours: float = 24.0) -> dict[str, Any]:
        """Project future cost based on recent usage patterns.

        Looks at usage from the last `hours` period and extrapolates.
        """
        now = time.time()
        since = now - (hours * 3600)
        summary = await self._storage.get_usage_summary(agent_id, since)

        total_cost = summary["total_cost"]
        total_calls = summary["total_calls"]

        # Extrapolate to next 24h
        rate_per_hour = total_cost / hours if hours > 0 else 0
        projected_24h = rate_per_hour * 24

        return {
            "period_hours": hours,
            "total_cost_in_period": total_cost,
            "total_calls_in_period": total_calls,
            "rate_per_hour": round(rate_per_hour, 4),
            "projected_24h_cost": round(projected_24h, 4),
        }


def require_credits(tracker: UsageTracker, cost: float = 1.0) -> Callable:
    """Standalone decorator that requires credits before execution.

    This is a convenience wrapper around tracker.metered with require_balance=True.

    Usage::

        @require_credits(tracker, cost=5)
        async def expensive_tool(agent_id, params):
            ...
    """
    return tracker.metered(cost=cost, require_balance=True)
