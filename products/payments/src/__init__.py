"""a2a-payments: Agent-to-Agent Payment System.

Provides payment intents, escrow, subscriptions, and settlement
on top of the a2a-billing wallet layer.
"""

from .engine import PaymentEngine
from .models import (
    Escrow,
    EscrowStatus,
    IntentStatus,
    PaymentIntent,
    Settlement,
    Subscription,
    SubscriptionInterval,
    SubscriptionStatus,
)
from .storage import PaymentStorage

__all__ = [
    "Escrow",
    "EscrowStatus",
    "IntentStatus",
    "PaymentEngine",
    "PaymentIntent",
    "PaymentStorage",
    "Settlement",
    "Subscription",
    "SubscriptionInterval",
    "SubscriptionStatus",
]

__version__ = "0.2.0"
