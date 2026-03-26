"""SubscriptionScheduler: processes due subscriptions on a schedule.

Handles charging due subscriptions and managing insufficient balance scenarios.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from payments.engine import PaymentEngine
from payments.models import Settlement, SubscriptionStatus
from payments.storage import PaymentStorage

from src.wallet import InsufficientCreditsError

logger = logging.getLogger(__name__)


@dataclass
class ChargeResult:
    """Result of a single subscription charge attempt."""

    subscription_id: str
    success: bool
    settlement: Settlement | None = None
    error: str | None = None


@dataclass
class SchedulerRunResult:
    """Result of a single scheduler run."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    suspended: int = 0
    expired_escrows: int = 0
    results: list[ChargeResult] = field(default_factory=list)


@dataclass
class SubscriptionScheduler:
    """Processes due subscriptions and expired escrows.

    Usage::

        scheduler = SubscriptionScheduler(engine=engine)
        result = await scheduler.process_due()  # one-shot
        # or
        await scheduler.run(interval=60)  # polling loop
    """

    engine: PaymentEngine

    async def process_due(self, now: float | None = None) -> SchedulerRunResult:
        """Process all due subscriptions and expired escrows.

        Returns a SchedulerRunResult summarizing what happened.
        """
        if now is None:
            now = time.time()

        result = SchedulerRunResult()

        # 1. Process expired escrows
        expired = await self.engine.process_expired_escrows()
        result.expired_escrows = len(expired)

        # 2. Process due subscriptions
        due_subs = await self.engine.storage.get_due_subscriptions(now)
        for sub_data in due_subs:
            sub_id = sub_data["id"]
            result.processed += 1

            charge_result = ChargeResult(subscription_id=sub_id, success=False)
            try:
                settlement = await self.engine.charge_subscription(sub_id)
                charge_result.success = True
                charge_result.settlement = settlement
                result.succeeded += 1
            except InsufficientCreditsError as e:
                charge_result.error = str(e)
                result.suspended += 1
                logger.warning(
                    "Subscription %s suspended: insufficient balance for %s",
                    sub_id, sub_data["payer"],
                )
            except Exception as e:
                charge_result.error = str(e)
                result.failed += 1
                logger.error(
                    "Subscription %s charge failed: %s", sub_id, e,
                )

            result.results.append(charge_result)

        return result

    async def run(
        self,
        interval: float = 60.0,
        max_iterations: int | None = None,
    ) -> None:
        """Run the scheduler in a polling loop.

        Args:
            interval: Seconds between processing runs.
            max_iterations: If set, stop after this many iterations (for testing).
        """
        iterations = 0
        while True:
            try:
                run_result = await self.process_due()
                if run_result.processed > 0:
                    logger.info(
                        "Scheduler run: processed=%d succeeded=%d failed=%d suspended=%d escrows_expired=%d",
                        run_result.processed,
                        run_result.succeeded,
                        run_result.failed,
                        run_result.suspended,
                        run_result.expired_escrows,
                    )
            except Exception:
                logger.exception("Scheduler run failed")

            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break

            await asyncio.sleep(interval)
