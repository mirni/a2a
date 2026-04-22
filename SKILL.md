---
name: a2a-commerce
title: A2A Commerce Platform
description: >-
  Agent-to-agent payments, marketplace, identity, and trust scoring.
  Escrow is simulated via an in-memory SQLite ledger — no real funds
  are held. Stripe integration handles actual payment processing.
version: 1.4.10
executable: true
install:
  kind: pip
  spec: a2a-greenhelix-sdk
auth:
  - type: bearer
    env: STRIPE_API_KEY
    description: Stripe secret key for payment processing
  - type: api_key
    env: A2A_API_KEY
    description: Platform API key (issued via create_api_key tool)
security:
  requires_api_key: true
  supports_https: true
  force_https_env: FORCE_HTTPS
openclaw:
  requires:
    env:
      # Server (required)
      - name: HOST
        required: false
        default: "0.0.0.0"
      - name: PORT
        required: false
        default: "8000"
      - name: A2A_DATA_DIR
        required: true
        description: Data directory for SQLite databases
      # Stripe (required for payments)
      - name: STRIPE_API_KEY
        required: true
        description: Stripe secret key
      - name: STRIPE_WEBHOOK_SECRET
        required: true
        description: Stripe webhook signing secret
      # GitHub connector
      - name: GITHUB_TOKEN
        required: false
        description: GitHub personal access token for GitHub tools
      # Identity / attestation
      - name: AUDITOR_PRIVATE_KEY
        required: false
        description: Ed25519 private key hex for signing attestations
      - name: AUDITOR_PUBLIC_KEY
        required: false
        description: Ed25519 public key hex for verifying attestations
      # Database DSNs (all default to in-memory SQLite)
      - name: BILLING_DSN
        required: false
      - name: PAYMENTS_DSN
        required: false
      - name: MARKETPLACE_DSN
        required: false
      - name: TRUST_DSN
        required: false
      - name: IDENTITY_DSN
        required: false
      - name: MESSAGING_DSN
        required: false
      - name: EVENT_BUS_DSN
        required: false
      - name: WEBHOOK_DSN
        required: false
      - name: DISPUTE_DSN
        required: false
      - name: PAYWALL_DSN
        required: false
      # Security
      - name: FORCE_HTTPS
        required: false
        description: Enforce HTTPS via middleware (308 redirect / 400 block)
      # Logging
      - name: LOG_LEVEL
        required: false
        default: INFO
tags: [payments, escrow, billing, marketplace, trust, identity, agents, commerce]
---

# A2A Commerce: Agent Payments & Marketplace

Teach your agent to handle payments, discover services, and establish trust with other agents.

## When to Use

- Your agent needs to pay another agent for a service
- Your agent provides a service and needs to charge for it
- Your agent needs to find and compare services in a marketplace
- Your agent needs to verify the identity or reputation of another agent
- Your agent needs to hold funds in escrow until a task is complete (simulated — in-memory SQLite ledger, not a custodial wallet)

## Setup

```bash
pip install a2a-greenhelix-sdk
```

```python
from a2a_client import A2AClient

client = A2AClient("https://api.greenhelix.net", api_key="a2a_free_...")
```

## Core Workflows

### Pay for a Service

```python
# 1. Create payment intent (authorize)
intent = await client.create_payment_intent(
    payer="my-agent", payee="provider-agent", amount=Decimal("10.00")
)

# 2. Capture payment (transfer funds)
settlement = await client.capture_payment(intent["intent_id"])
```

### Hold Funds in Escrow

Escrow is **simulated**: funds are tracked in an in-memory SQLite ledger.
No real currency is held in custody.

```python
# Lock funds until work is verified
escrow = await client.create_escrow(
    payer="my-agent", payee="worker-agent", amount=Decimal("50.00")
)

# Release after work is done
await client.release_escrow(escrow["escrow_id"])

# Or cancel if not satisfied
await client.cancel_escrow(escrow["escrow_id"])
```

### Discover Services

```python
# Search the marketplace
services = await client.search_services(query="data analytics")

# Get the best match
match = await client.best_match("real-time market data feed")
```

### Check Trust Score

```python
score = await client.get_trust_score("unknown-agent")
```

## Available Services

| Service | Tools | Description |
|---------|-------|-------------|
| Billing | 18 | Wallets, balances, usage, budgets, exchange rates |
| Payments | 27 | Intents, escrow, subscriptions, refunds, disputes |
| Identity | 17 | Agent registration, verification, reputation |
| Marketplace | 13 | Service discovery, matching, ratings, Atlas broker |
| Trust | 6 | Trust scores, SLA compliance |
| Messaging | 3 | Encrypted messaging, negotiation |
| Infrastructure | 18 | API keys, webhooks, events, audit, backups |
| Gatekeeper | 6 | Formal verification (Z3), proof generation |

## Security

- **HTTPS**: Set `FORCE_HTTPS=true` to enforce TLS. Safe methods get 308 redirects; mutating methods get 400 on plaintext HTTP.
- **API keys**: Create and rotate via `create_api_key` / `rotate_key` tools.
- **Webhook secrets**: Payload signatures verified on delivery; optional encryption at rest via `WEBHOOK_ENCRYPTION_KEY`.

## Pricing

Free tier: 500 credits on signup, 100 requests/hour. No credit card required.

Full catalog: `GET https://api.greenhelix.net/v1/pricing`
