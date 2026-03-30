"""PaymentEngine: orchestrates all payment flows.

Uses the billing Wallet for actual fund transfers and PaymentStorage for
payment-specific records. All monetary operations are atomic via transactions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from payments.models import (
    Escrow,
    EscrowStatus,
    IntentStatus,
    PaymentIntent,
    Refund,
    Settlement,
    SettlementStatus,
    Subscription,
    SubscriptionInterval,
    SubscriptionStatus,
)
from payments.storage import PaymentStorage

# Import InsufficientCreditsError from billing layer
from src.wallet import InsufficientCreditsError

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PaymentError(Exception):
    """Base exception for payment errors."""


class IntentNotFoundError(PaymentError):
    """Raised when a payment intent is not found."""


class EscrowNotFoundError(PaymentError):
    """Raised when an escrow is not found."""


class SubscriptionNotFoundError(PaymentError):
    """Raised when a subscription is not found."""


class SettlementNotFoundError(PaymentError):
    """Raised when a settlement is not found."""


class InvalidStateError(PaymentError):
    """Raised when an operation is attempted on an object in the wrong state."""


class DuplicateIntentError(PaymentError):
    """Raised when an idempotency key collision is detected."""

    def __init__(self, existing_intent: PaymentIntent) -> None:
        self.existing_intent = existing_intent
        super().__init__(f"Duplicate intent with idempotency key; existing id={existing_intent.id}")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class PaymentEngine:
    """Orchestrates payment intents, escrow, subscriptions, and settlements.

    Args:
        storage: PaymentStorage instance (must be connected).
        wallet: Billing Wallet instance (must have connected storage).
    """

    storage: PaymentStorage
    wallet: Any  # billing Wallet — typed as Any to avoid hard import dependency

    # -------------------------------------------------------------------
    # Payment Intents
    # -------------------------------------------------------------------

    async def create_intent(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PaymentIntent:
        """Create a payment intent. If idempotency_key already exists, return existing."""
        if amount <= 0:
            raise PaymentError("Amount must be positive")
        if payer == payee:
            raise PaymentError("Payer and payee must be different agents")

        # Idempotency check
        if idempotency_key is not None:
            existing = await self.storage.get_intent_by_idempotency_key(idempotency_key)
            if existing is not None:
                return PaymentIntent(**existing)

        intent = PaymentIntent(
            payer=payer,
            payee=payee,
            amount=amount,
            description=description,
            idempotency_key=idempotency_key,
            metadata=metadata or {},
        )
        await self.storage.insert_intent(intent.model_dump())
        return intent

    async def capture(self, intent_id: str) -> Settlement:
        """Capture a pending intent: move funds from payer to payee.

        Transitions: pending -> settled (atomically).
        """
        intent_data = await self.storage.get_intent(intent_id)
        if intent_data is None:
            raise IntentNotFoundError(f"Intent {intent_id} not found")

        intent = PaymentIntent(**intent_data)
        if intent.status != IntentStatus.PENDING:
            raise InvalidStateError(f"Cannot capture intent in state '{intent.status.value}'; must be 'pending'")

        # Transfer funds: withdraw from payer, deposit to payee
        amount = float(intent.amount)
        await self.wallet.withdraw(
            intent.payer,
            amount,
            description=f"payment:{intent.id}",
        )
        await self.wallet.deposit(
            intent.payee,
            amount,
            description=f"payment:{intent.id}",
        )

        # Create settlement record
        settlement = Settlement(
            payer=intent.payer,
            payee=intent.payee,
            amount=intent.amount,
            source_type="intent",
            source_id=intent.id,
            description=intent.description,
        )
        await self.storage.insert_settlement(settlement.model_dump())

        # Update intent status to settled
        await self.storage.update_intent_status(intent.id, IntentStatus.SETTLED.value, settlement_id=settlement.id)

        return settlement

    async def void(self, intent_id: str) -> PaymentIntent:
        """Void a pending intent. No funds move."""
        intent_data = await self.storage.get_intent(intent_id)
        if intent_data is None:
            raise IntentNotFoundError(f"Intent {intent_id} not found")

        intent = PaymentIntent(**intent_data)
        if intent.status != IntentStatus.PENDING:
            raise InvalidStateError(f"Cannot void intent in state '{intent.status.value}'; must be 'pending'")

        await self.storage.update_intent_status(intent.id, IntentStatus.VOIDED.value)
        intent.status = IntentStatus.VOIDED
        intent.updated_at = time.time()
        return intent

    async def partial_capture(self, intent_id: str, amount: float) -> tuple[Settlement, float]:
        """Partially capture a pending intent.

        Validates amount <= intent.amount, creates a settlement for the
        partial amount, and updates (or voids) the intent.
        """
        intent_data = await self.storage.get_intent(intent_id)
        if intent_data is None:
            raise IntentNotFoundError(f"Intent {intent_id} not found")

        intent = PaymentIntent(**intent_data)
        if intent.status != IntentStatus.PENDING:
            raise InvalidStateError(f"Cannot capture intent in state '{intent.status.value}'; must be 'pending'")

        if amount <= 0:
            raise PaymentError("Amount must be positive")
        intent_amount_f = float(intent.amount)
        if amount > intent_amount_f:
            raise PaymentError(f"Capture amount {amount} exceeds intent amount {intent_amount_f}")

        # Transfer the partial amount
        await self.wallet.withdraw(
            intent.payer,
            amount,
            description=f"partial_capture:{intent.id}",
        )
        await self.wallet.deposit(
            intent.payee,
            amount,
            description=f"partial_capture:{intent.id}",
        )

        # Create settlement for the partial amount
        settlement = Settlement(
            payer=intent.payer,
            payee=intent.payee,
            amount=amount,
            source_type="intent",
            source_id=intent.id,
            description=intent.description,
        )
        await self.storage.insert_settlement(settlement.model_dump())

        remaining = float(Decimal(str(intent_amount_f)) - Decimal(str(amount)))
        if remaining <= 0:
            # Fully captured - mark as settled
            await self.storage.update_intent_status(intent.id, IntentStatus.SETTLED.value, settlement_id=settlement.id)
        else:
            # Update the intent with the remaining amount
            await self.storage.update_intent_amount(intent.id, remaining)

        return settlement, remaining

    async def get_intent(self, intent_id: str) -> PaymentIntent:
        """Retrieve a payment intent by ID."""
        data = await self.storage.get_intent(intent_id)
        if data is None:
            raise IntentNotFoundError(f"Intent {intent_id} not found")
        return PaymentIntent(**data)

    # -------------------------------------------------------------------
    # Settlement Refunds
    # -------------------------------------------------------------------

    async def refund_settlement(
        self,
        settlement_id: str,
        amount: Decimal | None = None,
        reason: str = "",
    ) -> Refund:
        """Refund a settled payment (full or partial).

        Args:
            settlement_id: ID of the settlement to refund.
            amount: Amount to refund. If None, refunds the remaining (un-refunded) balance.
            reason: Optional reason for the refund.

        Returns:
            A Refund object with the details of this refund.

        Raises:
            SettlementNotFoundError: If settlement_id does not exist.
            InvalidStateError: If the settlement is already fully refunded.
            PaymentError: If amount is zero, negative, or exceeds the remaining refundable balance.
        """
        settlement_data = await self.storage.get_settlement(settlement_id)
        if settlement_data is None:
            raise SettlementNotFoundError(f"Settlement {settlement_id} not found")

        settlement = Settlement(**settlement_data)

        # Block if already fully refunded
        if settlement.status == SettlementStatus.REFUNDED:
            raise InvalidStateError(
                f"Settlement {settlement_id} is already fully refunded"
            )

        # Calculate remaining refundable amount
        total_refunded = await self.storage.get_total_refunded(settlement_id)
        remaining = settlement.amount - total_refunded

        if amount is not None:
            # Validate explicit amount
            if amount <= 0:
                raise PaymentError("Refund amount must be positive")
            if amount > remaining:
                raise PaymentError(
                    f"Refund amount {amount} exceeds remaining refundable balance {remaining}"
                )
            refund_amount = amount
        else:
            # Full refund of remaining
            refund_amount = remaining

        # Atomic fund transfer: withdraw from payee, deposit to payer
        await self.wallet.withdraw(
            settlement.payee,
            float(refund_amount),
            description=f"refund:{settlement_id}",
        )
        await self.wallet.deposit(
            settlement.payer,
            float(refund_amount),
            description=f"refund:{settlement_id}",
        )

        # Create refund record
        refund = Refund(
            settlement_id=settlement_id,
            amount=refund_amount,
            reason=reason,
        )
        await self.storage.insert_refund(refund.model_dump())

        # Update settlement status
        new_total_refunded = total_refunded + refund_amount
        if new_total_refunded >= settlement.amount:
            await self.storage.update_settlement_status(
                settlement_id, SettlementStatus.REFUNDED.value
            )
        else:
            await self.storage.update_settlement_status(
                settlement_id, SettlementStatus.PARTIALLY_REFUNDED.value
            )

        return refund

    # -------------------------------------------------------------------
    # Escrow
    # -------------------------------------------------------------------

    async def create_escrow(
        self,
        payer: str,
        payee: str,
        amount: float,
        description: str = "",
        timeout_hours: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Escrow:
        """Create an escrow: withdraw funds from payer and hold them."""
        if amount <= 0:
            raise PaymentError("Amount must be positive")
        if payer == payee:
            raise PaymentError("Payer and payee must be different agents")

        timeout_at = None
        if timeout_hours is not None:
            if timeout_hours <= 0:
                raise PaymentError("Timeout hours must be positive")
            timeout_at = time.time() + (timeout_hours * 3600)

        # Withdraw funds from payer (locks them)
        await self.wallet.withdraw(
            payer,
            amount,
            description=f"escrow_hold:{payer}->{payee}",
        )

        escrow = Escrow(
            payer=payer,
            payee=payee,
            amount=amount,
            description=description,
            timeout_at=timeout_at,
            metadata=metadata or {},
        )
        await self.storage.insert_escrow(escrow.model_dump())
        return escrow

    async def release_escrow(self, escrow_id: str) -> Settlement:
        """Release escrowed funds to the payee."""
        escrow_data = await self.storage.get_escrow(escrow_id)
        if escrow_data is None:
            raise EscrowNotFoundError(f"Escrow {escrow_id} not found")

        escrow = Escrow(**escrow_data)
        if escrow.status != EscrowStatus.HELD:
            raise InvalidStateError(f"Cannot release escrow in state '{escrow.status.value}'; must be 'held'")

        # Deposit to payee
        escrow_amount = float(escrow.amount)
        await self.wallet.deposit(
            escrow.payee,
            escrow_amount,
            description=f"escrow_release:{escrow.id}",
        )

        # Create settlement
        settlement = Settlement(
            payer=escrow.payer,
            payee=escrow.payee,
            amount=escrow.amount,
            source_type="escrow",
            source_id=escrow.id,
            description=escrow.description,
        )
        await self.storage.insert_settlement(settlement.model_dump())

        # Update escrow status
        await self.storage.update_escrow_status(escrow.id, EscrowStatus.SETTLED.value, settlement_id=settlement.id)

        return settlement

    async def refund_escrow(self, escrow_id: str) -> Escrow:
        """Refund escrowed funds back to the payer."""
        escrow_data = await self.storage.get_escrow(escrow_id)
        if escrow_data is None:
            raise EscrowNotFoundError(f"Escrow {escrow_id} not found")

        escrow = Escrow(**escrow_data)
        if escrow.status != EscrowStatus.HELD:
            raise InvalidStateError(f"Cannot refund escrow in state '{escrow.status.value}'; must be 'held'")

        # Return funds to payer
        await self.wallet.deposit(
            escrow.payer,
            float(escrow.amount),
            description=f"escrow_refund:{escrow.id}",
        )

        await self.storage.update_escrow_status(escrow.id, EscrowStatus.REFUNDED.value)
        escrow.status = EscrowStatus.REFUNDED
        escrow.updated_at = time.time()
        return escrow

    async def expire_escrow(self, escrow_id: str) -> Escrow:
        """Expire an escrow that has exceeded its timeout. Refunds the payer."""
        escrow_data = await self.storage.get_escrow(escrow_id)
        if escrow_data is None:
            raise EscrowNotFoundError(f"Escrow {escrow_id} not found")

        escrow = Escrow(**escrow_data)
        if escrow.status != EscrowStatus.HELD:
            raise InvalidStateError(f"Cannot expire escrow in state '{escrow.status.value}'; must be 'held'")

        # Return funds to payer
        await self.wallet.deposit(
            escrow.payer,
            float(escrow.amount),
            description=f"escrow_expired:{escrow.id}",
        )

        await self.storage.update_escrow_status(escrow.id, EscrowStatus.EXPIRED.value)
        escrow.status = EscrowStatus.EXPIRED
        escrow.updated_at = time.time()
        return escrow

    async def get_escrow(self, escrow_id: str) -> Escrow:
        """Retrieve an escrow by ID."""
        data = await self.storage.get_escrow(escrow_id)
        if data is None:
            raise EscrowNotFoundError(f"Escrow {escrow_id} not found")
        return Escrow(**data)

    async def process_expired_escrows(self) -> list[Escrow]:
        """Find and expire all escrows that have exceeded their timeout."""
        expired_data = await self.storage.get_expired_escrows()
        results = []
        for data in expired_data:
            escrow = await self.expire_escrow(data["id"])
            results.append(escrow)
        return results

    # -------------------------------------------------------------------
    # Subscriptions
    # -------------------------------------------------------------------

    async def create_subscription(
        self,
        payer: str,
        payee: str,
        amount: float,
        interval: str,
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Subscription:
        """Create a recurring payment subscription."""
        if amount <= 0:
            raise PaymentError("Amount must be positive")
        if payer == payee:
            raise PaymentError("Payer and payee must be different agents")

        # Validate interval
        try:
            sub_interval = SubscriptionInterval(interval)
        except ValueError:
            valid = [i.value for i in SubscriptionInterval]
            raise PaymentError(f"Invalid interval '{interval}'; must be one of {valid}") from None

        sub = Subscription(
            payer=payer,
            payee=payee,
            amount=amount,
            interval=sub_interval,
            description=description,
            metadata=metadata or {},
        )
        # Set next_charge_at to the first billing cycle from now
        sub.next_charge_at = sub.compute_next_charge()

        await self.storage.insert_subscription(sub.model_dump())
        return sub

    async def cancel_subscription(self, sub_id: str, cancelled_by: str | None = None) -> Subscription:
        """Cancel an active or suspended subscription."""
        sub_data = await self.storage.get_subscription(sub_id)
        if sub_data is None:
            raise SubscriptionNotFoundError(f"Subscription {sub_id} not found")

        sub = Subscription(**sub_data)
        if sub.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.SUSPENDED):
            raise InvalidStateError(
                f"Cannot cancel subscription in state '{sub.status.value}'; must be 'active' or 'suspended'"
            )

        await self.storage.update_subscription(
            sub.id,
            {
                "status": SubscriptionStatus.CANCELLED.value,
                "cancelled_by": cancelled_by,
            },
        )
        sub.status = SubscriptionStatus.CANCELLED
        sub.cancelled_by = cancelled_by
        sub.updated_at = time.time()
        return sub

    async def suspend_subscription(self, sub_id: str) -> Subscription:
        """Suspend a subscription (e.g., due to insufficient balance)."""
        sub_data = await self.storage.get_subscription(sub_id)
        if sub_data is None:
            raise SubscriptionNotFoundError(f"Subscription {sub_id} not found")

        sub = Subscription(**sub_data)
        if sub.status != SubscriptionStatus.ACTIVE:
            raise InvalidStateError(f"Cannot suspend subscription in state '{sub.status.value}'; must be 'active'")

        await self.storage.update_subscription(
            sub.id,
            {
                "status": SubscriptionStatus.SUSPENDED.value,
            },
        )
        sub.status = SubscriptionStatus.SUSPENDED
        sub.updated_at = time.time()
        return sub

    async def reactivate_subscription(self, sub_id: str) -> Subscription:
        """Reactivate a suspended subscription."""
        sub_data = await self.storage.get_subscription(sub_id)
        if sub_data is None:
            raise SubscriptionNotFoundError(f"Subscription {sub_id} not found")

        sub = Subscription(**sub_data)
        if sub.status != SubscriptionStatus.SUSPENDED:
            raise InvalidStateError(
                f"Cannot reactivate subscription in state '{sub.status.value}'; must be 'suspended'"
            )

        await self.storage.update_subscription(
            sub.id,
            {
                "status": SubscriptionStatus.ACTIVE.value,
            },
        )
        sub.status = SubscriptionStatus.ACTIVE
        sub.updated_at = time.time()
        return sub

    async def charge_subscription(self, sub_id: str) -> Settlement:
        """Process a single charge for a subscription.

        Withdraws from payer, deposits to payee, creates settlement.
        If payer has insufficient balance, suspends the subscription.
        """
        sub_data = await self.storage.get_subscription(sub_id)
        if sub_data is None:
            raise SubscriptionNotFoundError(f"Subscription {sub_id} not found")

        sub = Subscription(**sub_data)
        if sub.status != SubscriptionStatus.ACTIVE:
            raise InvalidStateError(f"Cannot charge subscription in state '{sub.status.value}'; must be 'active'")

        # Attempt to transfer funds
        sub_amount = float(sub.amount)
        try:
            await self.wallet.withdraw(
                sub.payer,
                sub_amount,
                description=f"subscription:{sub.id}",
            )
        except InsufficientCreditsError:
            # Suspend the subscription
            await self.storage.update_subscription(
                sub.id,
                {
                    "status": SubscriptionStatus.SUSPENDED.value,
                },
            )
            raise

        await self.wallet.deposit(
            sub.payee,
            sub_amount,
            description=f"subscription:{sub.id}",
        )

        # Create settlement
        settlement = Settlement(
            payer=sub.payer,
            payee=sub.payee,
            amount=sub.amount,
            source_type="subscription",
            source_id=sub.id,
            description=sub.description,
        )
        await self.storage.insert_settlement(settlement.model_dump())

        # Update subscription
        now = time.time()
        new_sub = Subscription(**sub.model_dump())
        new_sub.last_charged_at = now
        new_sub.charge_count = sub.charge_count + 1
        new_sub.next_charge_at = new_sub.compute_next_charge()

        await self.storage.update_subscription(
            sub.id,
            {
                "last_charged_at": new_sub.last_charged_at,
                "charge_count": new_sub.charge_count,
                "next_charge_at": new_sub.next_charge_at,
            },
        )

        return settlement

    async def get_subscription(self, sub_id: str) -> Subscription:
        """Retrieve a subscription by ID."""
        data = await self.storage.get_subscription(sub_id)
        if data is None:
            raise SubscriptionNotFoundError(f"Subscription {sub_id} not found")
        return Subscription(**data)

    # -------------------------------------------------------------------
    # Payment History
    # -------------------------------------------------------------------

    async def get_payment_history(
        self,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get unified payment history for an agent."""
        return await self.storage.get_payment_history(agent_id, limit, offset)
