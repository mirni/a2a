# Agent Payments in 5 Minutes

*How to set up wallet-based payments between AI agents using the A2A Commerce Platform.*

## Introduction

AI agents need to pay each other. Whether it's an analytics agent buying data from a market-data agent, or a trading bot paying for signal processing, the A2A Commerce Platform makes agent-to-agent payments as simple as three API calls.

This tutorial walks you through creating wallets, depositing funds, and executing your first payment intent -- all in under 5 minutes.

## Prerequisites

- A running A2A gateway (`python -m gateway.src.main`)
- Python 3.11+ with `httpx` installed
- Two agent IDs (we'll create them below)

## Step 1: Register Agents and Create Wallets

Every agent needs an identity and a wallet. Registration gives you both -- plus 500 free credits to start.

```python
import httpx

BASE = "http://localhost:8000"

async def setup():
    async with httpx.AsyncClient(base_url=BASE) as client:
        # Register the buyer agent
        buyer = await client.post("/tools/register_agent", json={
            "agent_id": "buyer-agent-01"
        })
        print(f"Buyer registered: {buyer.json()}")

        # Register the seller agent
        seller = await client.post("/tools/register_agent", json={
            "agent_id": "seller-agent-01"
        })
        print(f"Seller registered: {seller.json()}")
```

Both agents automatically receive a wallet with 500 free credits on signup.

## Step 2: Check Balances

Verify the wallets were funded:

```python
async def check_balances():
    async with httpx.AsyncClient(base_url=BASE) as client:
        buyer_bal = await client.post("/tools/get_balance", json={
            "agent_id": "buyer-agent-01"
        })
        print(f"Buyer balance: {buyer_bal.json()['balance']} credits")
        # Output: Buyer balance: 500.0 credits

        seller_bal = await client.post("/tools/get_balance", json={
            "agent_id": "seller-agent-01"
        })
        print(f"Seller balance: {seller_bal.json()['balance']} credits")
```

## Step 3: Create a Payment Intent

A payment intent captures the *authorization* to move funds. Think of it as a two-phase commit: first you authorize, then you capture.

```python
async def pay_for_service():
    async with httpx.AsyncClient(base_url=BASE) as client:
        # Create a payment intent (authorize 10 credits)
        intent = await client.post("/tools/create_intent", json={
            "payer": "buyer-agent-01",
            "payee": "seller-agent-01",
            "amount": 10.0,
            "memo": "Market data feed - March 2026"
        })
        intent_id = intent.json()["intent_id"]
        print(f"Intent created: {intent_id}")

        # Capture the payment (move the funds)
        capture = await client.post("/tools/capture_intent", json={
            "intent_id": intent_id
        })
        print(f"Payment captured: {capture.json()}")
```

After capture, 10 credits move from the buyer's wallet to the seller's wallet. The transaction is atomic and recorded in both agents' ledgers.

## Step 4: Verify the Transfer

```python
async def verify():
    async with httpx.AsyncClient(base_url=BASE) as client:
        buyer_bal = await client.post("/tools/get_balance", json={
            "agent_id": "buyer-agent-01"
        })
        print(f"Buyer: {buyer_bal.json()['balance']} credits")
        # Output: Buyer: 490.0 credits

        seller_bal = await client.post("/tools/get_balance", json={
            "agent_id": "seller-agent-01"
        })
        print(f"Seller: {seller_bal.json()['balance']} credits")
        # Output: Seller: 510.0 credits
```

## Complete Example

Here's everything in one runnable script:

```python
import asyncio
import httpx

BASE = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient(base_url=BASE) as c:
        # 1. Register agents
        await c.post("/tools/register_agent", json={"agent_id": "buyer-01"})
        await c.post("/tools/register_agent", json={"agent_id": "seller-01"})

        # 2. Create payment intent
        resp = await c.post("/tools/create_intent", json={
            "payer": "buyer-01",
            "payee": "seller-01",
            "amount": 25.0,
            "memo": "Signal processing job #42"
        })
        intent_id = resp.json()["intent_id"]

        # 3. Capture payment
        await c.post("/tools/capture_intent", json={"intent_id": intent_id})

        # 4. Check balances
        buyer = await c.post("/tools/get_balance", json={"agent_id": "buyer-01"})
        seller = await c.post("/tools/get_balance", json={"agent_id": "seller-01"})
        print(f"Buyer: {buyer.json()['balance']}, Seller: {seller.json()['balance']}")

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

*Built with the A2A Commerce Platform. See the [full API catalog](../../gateway/src/catalog.json) for all 100+ available tools.*
