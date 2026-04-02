# Agent Payments in 5 Minutes

*How to set up wallet-based payments between AI agents using the A2A Commerce Platform.*

## Introduction

AI agents need to pay each other. Whether it's an analytics agent buying data from a market-data agent, or a trading bot paying for signal processing, the A2A Commerce Platform makes agent-to-agent payments as simple as three API calls.

This tutorial walks you through creating wallets, depositing funds, and executing your first payment intent -- all in under 5 minutes.

## Prerequisites

- A running A2A gateway (`python gateway/main.py`)
- Python 3.12+ with `a2a-sdk` installed (`pip install a2a-sdk`)
- Two agent IDs (we'll create them below)

## Step 1: Register Agents and Create Wallets

Every agent needs an identity and a wallet. Registration gives you both -- plus 500 free credits to start.

```python
from a2a_client import A2AClient

BASE = "http://localhost:8000"

async def setup():
    async with A2AClient(BASE, api_key="a2a_free_...") as client:
        # Register the buyer agent
        buyer = await client.register_agent("buyer-agent-01")
        print(f"Buyer registered: {buyer}")

        # Register the seller agent
        seller = await client.register_agent("seller-agent-01")
        print(f"Seller registered: {seller}")
```

Both agents automatically receive a wallet with 500 free credits on signup.

## Step 2: Check Balances

Verify the wallets were funded:

```python
async def check_balances():
    async with A2AClient(BASE, api_key="a2a_free_...") as client:
        buyer_bal = await client.get_balance("buyer-agent-01")
        print(f"Buyer balance: {buyer_bal} credits")
        # Output: Buyer balance: 500.0 credits

        seller_bal = await client.get_balance("seller-agent-01")
        print(f"Seller balance: {seller_bal} credits")
```

## Step 3: Create a Payment Intent

A payment intent captures the *authorization* to move funds. Think of it as a two-phase commit: first you authorize, then you capture.

```python
async def pay_for_service():
    async with A2AClient(BASE, api_key="a2a_free_...") as client:
        # Create a payment intent (authorize 10 credits)
        intent = await client.create_payment_intent(
            payer="buyer-agent-01",
            payee="seller-agent-01",
            amount=10.0,
            memo="Market data feed - March 2026",
        )
        print(f"Intent created: {intent['intent_id']}")

        # Capture the payment (move the funds)
        settlement = await client.capture_payment(intent["intent_id"])
        print(f"Payment captured: {settlement}")
```

After capture, 10 credits move from the buyer's wallet to the seller's wallet. The transaction is atomic and recorded in both agents' ledgers.

## Step 4: Verify the Transfer

```python
async def verify():
    async with A2AClient(BASE, api_key="a2a_free_...") as client:
        buyer_bal = await client.get_balance("buyer-agent-01")
        print(f"Buyer: {buyer_bal} credits")
        # Output: Buyer: 490.0 credits

        seller_bal = await client.get_balance("seller-agent-01")
        print(f"Seller: {seller_bal} credits")
        # Output: Seller: 510.0 credits
```

## Complete Example

Here's everything in one runnable script:

```python
import asyncio
from a2a_client import A2AClient

BASE = "http://localhost:8000"

async def main():
    async with A2AClient(BASE, api_key="a2a_free_...") as client:
        # 1. Register agents
        await client.register_agent("buyer-01")
        await client.register_agent("seller-01")

        # 2. Create payment intent
        intent = await client.create_payment_intent(
            payer="buyer-01",
            payee="seller-01",
            amount=25.0,
            memo="Signal processing job #42",
        )

        # 3. Capture payment
        await client.capture_payment(intent["intent_id"])

        # 4. Check balances
        buyer_bal = await client.get_balance("buyer-01")
        seller_bal = await client.get_balance("seller-01")
        print(f"Buyer: {buyer_bal}, Seller: {seller_bal}")

asyncio.run(main())
```

## What's Next?

- **Partial captures**: Capture less than the authorized amount with `partial_capture`
- **Refunds**: Reverse a payment with `refund_intent`
- **Subscriptions**: Set up recurring payments with `create_subscription`
- **Escrow**: Hold funds in escrow until conditions are met (see our [Escrow tutorial](./escrow-for-ai-service-contracts.md))
- **Budget caps**: Set spending limits with `set_budget_cap`

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Wallet** | Per-agent balance in atomic units (credits). Created on registration. |
| **Payment Intent** | Two-phase payment: authorize then capture. Supports partial capture and refund. |
| **Settlement** | Final transfer record after capture. Immutable ledger entry. |
| **Auto-reload** | Optional: automatically top up wallet when balance drops below threshold. |

---

*Built with the A2A Commerce Platform. See the [SDK Guide](../sdk-guide.md) for the full API reference.*
