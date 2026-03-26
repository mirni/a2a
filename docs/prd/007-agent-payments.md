# PRD-007: Agent-to-Agent Payment System

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

Agents can track usage and manage wallets (billing layer), but cannot pay each other. There is no mechanism for one agent to purchase a service from another agent, hold funds in escrow during multi-step tasks, or establish recurring payment contracts. This blocks the core A2A commerce thesis.

## Target Buyer

- Agent developers building multi-agent systems
- MCP server operators who want to monetize their tools
- Trading/analytics agents that consume paid data feeds

## Product Scope

### Payment Intents

An agent initiates a payment to another agent for a specific service:

```python
from a2a_payments import PaymentEngine

engine = PaymentEngine(storage=billing_storage)

# Agent A pays Agent B for a service
intent = await engine.create_intent(
    payer="agent-a",
    payee="agent-b",
    amount=10.0,
    description="market-data-query",
    idempotency_key="req-123",
)
# intent.status == "pending"

# After service delivery, settle
await engine.capture(intent.id)
# Funds move from agent-a wallet to agent-b wallet
```

### Escrow

For multi-step tasks, funds are held until completion:

```python
escrow = await engine.create_escrow(
    payer="agent-a",
    payee="agent-b",
    amount=50.0,
    description="data-pipeline-build",
    timeout_hours=24,
)
# Funds locked in agent-a wallet

# On success:
await engine.release_escrow(escrow.id)

# On failure/timeout:
await engine.refund_escrow(escrow.id)
```

### Subscription Contracts

Recurring payments between agents:

```python
contract = await engine.create_subscription(
    payer="agent-a",
    payee="agent-b",
    amount=100.0,
    interval="monthly",
    description="premium-data-feed",
)

# Engine auto-charges on schedule
# Contract can be cancelled by either party
await engine.cancel_subscription(contract.id, cancelled_by="agent-a")
```

### Components

- **PaymentEngine** — orchestrates all payment flows
  - `create_intent()` — initiate a payment
  - `capture()` / `void()` — settle or cancel a pending intent
  - `create_escrow()` / `release_escrow()` / `refund_escrow()` — hold-and-release
  - `create_subscription()` / `cancel_subscription()` — recurring payments
  - `get_payment_history()` — ledger for an agent

- **Payment Storage** — extends billing SQLite with:
  - `payment_intents` — intent records with status lifecycle
  - `escrows` — held funds with timeout tracking
  - `subscriptions` — recurring payment contracts
  - `settlements` — completed fund transfers

- **Trust Integration** — check payee trust score before large payments
  - Configurable trust threshold per payment amount
  - Warning (not block) for low-trust payees

## Status Lifecycle

```
Intent:  pending → captured → settled
                → voided
Escrow:  held → released → settled
              → refunded
              → expired (auto-refund on timeout)
Subscription: active → cancelled
                     → suspended (insufficient balance)
```

## Success Metrics

- 50+ payment intents created in first 30 days
- <100ms payment creation latency
- Zero double-charge incidents
- 10+ active subscriptions in 60 days

## Kill Criteria

- <10 payment intents in 30 days → no demand for A2A payments yet
- Double-charge or fund loss bugs → stop and fix before continuing
