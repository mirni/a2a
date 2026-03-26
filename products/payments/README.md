# Agent-to-Agent Payment System

Payment infrastructure for autonomous agent commerce. Provides payment intents, escrow, subscriptions, and settlement on top of the billing wallet layer.

## Components

| Component | Description |
|-----------|-------------|
| `PaymentEngine` | Orchestrates all payment flows: intents, escrow, subscriptions |
| `PaymentStorage` | SQLite persistence for payment records |
| `SubscriptionScheduler` | Automated processing of due subscriptions and expired escrows |

## Quick Start

```python
from payments.engine import PaymentEngine
from payments.storage import PaymentStorage
from src.storage import StorageBackend  # billing
from src.wallet import Wallet  # billing

# Initialize
billing_storage = StorageBackend("sqlite:///billing.db")
await billing_storage.connect()
wallet = Wallet(billing_storage)

payment_storage = PaymentStorage("sqlite:///payments.db")
await payment_storage.connect()

engine = PaymentEngine(storage=payment_storage, wallet=wallet)
```

## Payment Intents

```python
# Agent A pays Agent B
intent = await engine.create_intent(
    payer="agent-a", payee="agent-b", amount=10.0,
    description="data-query", idempotency_key="req-123",
)

# After service delivery
await engine.capture(intent.id)
# Funds: agent-a -10.0, agent-b +10.0

# Or cancel
await engine.void(intent.id)
```

## Escrow

```python
# Hold funds for multi-step task
escrow = await engine.create_escrow(
    payer="agent-a", payee="agent-b", amount=50.0,
    timeout_hours=24,
)

# On success: release to payee
await engine.release_escrow(escrow.id)

# On failure: refund to payer
await engine.refund_escrow(escrow.id)

# Auto-expire overdue escrows
await engine.process_expired_escrows()
```

## Subscriptions

```python
# Recurring payments
sub = await engine.create_subscription(
    payer="agent-a", payee="agent-b",
    amount=100.0, interval="monthly",
)

# Process due charges
await engine.charge_subscription(sub.id)

# Cancel
await engine.cancel_subscription(sub.id, cancelled_by="agent-a")
```

## Automated Scheduling

```python
from payments.scheduler import SubscriptionScheduler

scheduler = SubscriptionScheduler(engine=engine, interval_seconds=60)
result = await scheduler.process_due()
# result.processed, result.succeeded, result.failed, result.suspended
```
