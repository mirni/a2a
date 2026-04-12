"""PlanManager: monthly subscription plan management.

Handles subscribing agents to pricing plans, granting credits on each
billing cycle, and plan changes (upgrade/downgrade).

Plans are defined in pricing.json under "subscription_plans".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from payments.engine import PaymentEngine
from payments.models import Subscription
from shared_src.pricing_config import load_pricing_config

logger = logging.getLogger(__name__)

_pricing = load_pricing_config()

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

PLATFORM_AGENT = "platform"


class InvalidPlanError(Exception):
    """Raised when subscribing to a non-existent or non-self-service plan."""


class DuplicatePlanSubscriptionError(Exception):
    """Raised when an agent already has an active plan subscription."""


class NoPlanSubscriptionError(Exception):
    """Raised when operating on a non-existent plan subscription."""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PlanChargeResult:
    """Result of a single plan credit grant."""

    subscription_id: str
    success: bool
    error: str | None = None


@dataclass
class PlanProcessResult:
    """Result of processing due plan subscriptions."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[PlanChargeResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PlanManager
# ---------------------------------------------------------------------------


@dataclass
class PlanManager:
    """Manages monthly subscription plans.

    Plans differ from regular subscriptions: instead of payer→payee transfer,
    the platform grants credits to the subscriber on each billing cycle.
    """

    engine: PaymentEngine
    wallet: Any  # billing Wallet

    async def subscribe(self, agent_id: str, plan_id: str) -> Subscription:
        """Subscribe an agent to a pricing plan.

        Creates a subscription with payer="platform", payee=agent_id.
        Immediately grants the first cycle's credits.

        Raises:
            InvalidPlanError: Plan doesn't exist or is custom-only.
            DuplicatePlanSubscriptionError: Agent already has an active plan.
        """
        plan = _pricing.subscription_plans.get(plan_id)
        if plan is None:
            raise InvalidPlanError(f"Plan '{plan_id}' not found")
        if plan.get("custom"):
            raise InvalidPlanError(f"Plan '{plan_id}' is custom-only; contact sales")

        # Check for existing active plan
        existing = await self._get_active_subscription(agent_id)
        if existing is not None:
            raise DuplicatePlanSubscriptionError(
                f"Agent {agent_id} already has active plan '{existing.metadata.get('plan_id')}'"
            )

        credits_per_cycle = plan["credits_included"]

        # Create subscription record (payer=platform, payee=subscriber)
        sub = await self.engine.create_subscription(
            payer=PLATFORM_AGENT,
            payee=agent_id,
            amount=float(credits_per_cycle),
            interval=plan.get("billing_period", "monthly"),
            description=f"Plan: {plan_id}",
            metadata={
                "plan_id": plan_id,
                "credits_per_cycle": credits_per_cycle,
                "price_cents": plan.get("price_cents", 0),
                "tier": plan.get("tier", ""),
                "type": "plan_subscription",
            },
        )

        # Grant initial credits immediately
        await self._grant_credits(agent_id, credits_per_cycle, f"Plan {plan_id} — initial credits")

        return sub

    async def process_due(self, now: float | None = None) -> PlanProcessResult:
        """Process all due plan subscriptions, granting credits.

        Unlike regular subscriptions (which transfer between agents),
        plan subscriptions deposit credits from the platform.
        """
        if now is None:
            now = time.time()

        result = PlanProcessResult()

        due_subs = await self.engine.storage.get_due_subscriptions(now)
        for sub_data in due_subs:
            # Only process plan subscriptions
            metadata = sub_data.get("metadata") or {}
            if isinstance(metadata, str):
                import json

                metadata = json.loads(metadata)
            if metadata.get("type") != "plan_subscription":
                continue

            sub_id = sub_data["id"]
            result.processed += 1

            charge_result = PlanChargeResult(subscription_id=sub_id, success=False)
            try:
                agent_id = sub_data["payee"]
                credits = metadata["credits_per_cycle"]

                await self._grant_credits(agent_id, credits, f"Plan {metadata['plan_id']} — monthly credits")

                # Update subscription timestamps
                sub = await self.engine.get_subscription(sub_id)
                new_next = sub.compute_next_charge()
                await self.engine.storage.update_subscription(
                    sub_id,
                    {
                        "last_charged_at": now,
                        "charge_count": sub.charge_count + 1,
                        "next_charge_at": new_next,
                    },
                )

                charge_result.success = True
                result.succeeded += 1
            except Exception as e:
                charge_result.error = str(e)
                result.failed += 1
                logger.error("Plan subscription %s charge failed: %s", sub_id, e)

            result.results.append(charge_result)

        return result

    async def cancel(self, agent_id: str) -> Subscription:
        """Cancel an agent's active plan subscription.

        Raises NoPlanSubscriptionError if no active plan found.
        """
        sub = await self._get_active_subscription(agent_id)
        if sub is None:
            raise NoPlanSubscriptionError(f"No active plan subscription for {agent_id}")
        return await self.engine.cancel_subscription(sub.id, cancelled_by=agent_id)

    async def change_plan(self, agent_id: str, new_plan_id: str) -> Subscription:
        """Change an agent's plan (cancel old, subscribe to new).

        Grants the new plan's credits immediately.
        """
        await self.cancel(agent_id)
        return await self.subscribe(agent_id, new_plan_id)

    async def get_active_plan(self, agent_id: str) -> dict[str, Any] | None:
        """Return the active plan info for an agent, or None."""
        sub = await self._get_active_subscription(agent_id)
        if sub is None:
            return None

        plan_id = sub.metadata.get("plan_id", "")
        plan_config = _pricing.subscription_plans.get(plan_id, {})

        return {
            "plan_id": plan_id,
            "subscription_id": sub.id,
            "credits_per_cycle": sub.metadata.get("credits_per_cycle", 0),
            "price_cents": plan_config.get("price_cents", 0),
            "tier": plan_config.get("tier", ""),
            "billing_period": plan_config.get("billing_period", "monthly"),
            "status": sub.status.value,
            "next_charge_at": sub.next_charge_at,
        }

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    async def _get_active_subscription(self, agent_id: str) -> Subscription | None:
        """Find the active plan subscription for an agent."""
        subs = await self.engine.storage.list_subscriptions(agent_id=agent_id, status="active")
        for s in subs:
            metadata = s.get("metadata") or {}
            if isinstance(metadata, str):
                import json

                metadata = json.loads(metadata)
            if metadata.get("type") == "plan_subscription":
                return Subscription(**s)
        return None

    async def _grant_credits(self, agent_id: str, amount: float, description: str) -> float:
        """Deposit credits to the subscriber's wallet."""
        # lint-no-float-money: allow (wallet.deposit legacy float API, v1.2.9 ratchet)
        return await self.wallet.deposit(agent_id, float(amount), description)
