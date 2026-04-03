# External Audit: Live Payment Testing

**Target:** A2A Commerce Platform
**Sandbox:** `https://sandbox.greenhelix.net`
**Date:** 2026-04-03
**Scope:** Functional correctness of live wallets, payments, escrow, marketplace, and billing flows

---

## Environment

| Environment | URL | Notes |
|-------------|-----|-------|
| **Sandbox** | `https://sandbox.greenhelix.net` | Fresh databases on each deploy. Use this for testing. |
| Production | `https://api.greenhelix.net` | Real data. Do not use for destructive tests. |
| Swagger UI | `https://sandbox.greenhelix.net/docs` | Interactive API browser |
| OpenAPI Spec | `https://sandbox.greenhelix.net/v1/openapi.json` | Machine-readable spec |
| Pricing Catalog | `https://sandbox.greenhelix.net/v1/pricing` | All tools with costs and tiers |

All endpoints are behind Cloudflare (TLSv1.3). Authentication via `Authorization: Bearer <api_key>` or `X-API-Key: <api_key>`.

---

## Phase 0: Setup — Register Test Agents

Register two agents. Each gets a free-tier API key and a wallet with 500 credits.

```bash
# Agent A (payer)
curl -s -X POST https://sandbox.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "audit-payer"}' | jq .

# Save the api_key from the response:
# PAYER_KEY="a2a_free_..."

# Agent B (payee)
curl -s -X POST https://sandbox.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "audit-payee"}' | jq .

# Save the api_key from the response:
# PAYEE_KEY="a2a_free_..."
```

**Expected:** HTTP 201 with `{"agent_id": "...", "api_key": "a2a_free_...", "tier": "free", "balance": 500.0}`

**Verify:**
```bash
curl -s https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/balance \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
# Expected: {"agent_id": "audit-payer", "balance": 500.0, "currency": "CREDITS"}
```

---

## Phase 1: Wallet & Billing Operations

### Test 1.1 — Deposit credits

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/deposit \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "100.00"}' | jq .
```

**Expected:** Balance = 600.0. Response includes `transaction_id`.

### Test 1.2 — Idempotent deposit (same key = no double-credit)

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/deposit \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: deposit-001" \
  -d '{"amount": "50.00"}' | jq .

# Repeat the exact same request:
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/deposit \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: deposit-001" \
  -d '{"amount": "50.00"}' | jq .
```

**Expected:** Both return 200 with the same `transaction_id`. Balance increases by 50 only once (total 650.0).

### Test 1.3 — Withdraw credits

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/withdraw \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "25.00"}' | jq .
```

**Expected:** Balance = 625.0.

### Test 1.4 — Withdraw more than balance (should fail)

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/withdraw \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "9999.00"}' | jq .
```

**Expected:** HTTP 402 or 400 error (insufficient funds).

### Test 1.5 — Invalid amounts (should fail)

```bash
# Zero amount
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/deposit \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "0"}' | jq .

# Negative amount
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/deposit \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "-10.00"}' | jq .
```

**Expected:** HTTP 422 for both (Pydantic validation: `amount` must be `gt=0`).

### Test 1.6 — Transaction history

```bash
curl -s "https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/transactions?limit=10" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** Lists all previous transactions (signup_bonus, deposit, withdraw) in order.

### Test 1.7 — Budget caps

```bash
# Set a daily budget cap
curl -s -X PUT https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/budget \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"daily_cap": "100.00", "monthly_cap": "2000.00"}' | jq .

# Check budget status
curl -s https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/budget \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** Budget caps are saved and returned.

---

## Phase 2: Payment Intents (Authorize → Capture → Refund)

### Test 2.1 — Create payment intent

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "payer": "audit-payer",
    "payee": "audit-payee",
    "amount": "25.00",
    "description": "Audit test payment"
  }' | jq .

# Save: INTENT_ID="..."
```

**Expected:** HTTP 201 with `status: "pending"`. Payer balance is NOT yet deducted (authorize only).

### Test 2.2 — Capture payment

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents/$INTENT_ID/capture \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** `status: "captured"`. Payer balance decreases by 25.0, payee balance increases by 25.0.

**Verify balances:**
```bash
curl -s https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/balance \
  -H "Authorization: Bearer $PAYER_KEY" | jq .balance
curl -s https://sandbox.greenhelix.net/v1/billing/wallets/audit-payee/balance \
  -H "Authorization: Bearer $PAYEE_KEY" | jq .balance
```

### Test 2.3 — Refund captured payment

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents/$INTENT_ID/refund \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** `status: "refunded"`. Funds return to payer.

### Test 2.4 — Partial capture

```bash
# Create new intent for 100 credits
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"payer": "audit-payer", "payee": "audit-payee", "amount": "100.00"}' | jq .
# INTENT_ID2="..."

# Capture only 40
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents/$INTENT_ID2/partial-capture \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "40.00"}' | jq .
```

**Expected:** Settlement for 40.0. Remaining 60.0 released back to payer.

### Test 2.5 — Split payment

```bash
# Register a third agent
curl -s -X POST https://sandbox.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "audit-platform"}' | jq .
# PLATFORM_KEY="..."

curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents/split \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "payer": "audit-payer",
    "total_amount": "100.00",
    "splits": [
      {"payee": "audit-payee", "percentage": 80},
      {"payee": "audit-platform", "percentage": 20}
    ]
  }' | jq .
```

**Expected:** Intent created with split distribution.

### Test 2.6 — Payment by non-owner (should fail)

```bash
# Payee tries to capture payer's intent — should be forbidden
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents/$INTENT_ID/capture \
  -H "Authorization: Bearer $PAYEE_KEY" | jq .
```

**Expected:** HTTP 403 (only payer or admin can capture).

---

## Phase 3: Escrow (Hold → Release / Cancel)

### Test 3.1 — Create and release escrow

```bash
# Create escrow
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "payer": "audit-payer",
    "payee": "audit-payee",
    "amount": "50.00",
    "description": "Audit escrow test"
  }' | jq .
# ESCROW_ID="..."
```

**Expected:** HTTP 201 with `status: "held"`. Payer balance decreases by 50.

```bash
# Release escrow (funds go to payee)
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows/$ESCROW_ID/release \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** `status: "released"`. Payee balance increases by 50.

### Test 3.2 — Create and cancel escrow

```bash
# Create another escrow
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"payer": "audit-payer", "payee": "audit-payee", "amount": "30.00"}' | jq .
# ESCROW_ID2="..."

# Cancel (refund to payer)
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows/$ESCROW_ID2/cancel \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** `status: "cancelled"`. Payer balance restored.

### Test 3.3 — Payee cannot cancel escrow (BOLA check)

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows/$ESCROW_ID2/cancel \
  -H "Authorization: Bearer $PAYEE_KEY" | jq .
```

**Expected:** HTTP 403 (only payer can cancel).

### Test 3.4 — Performance-gated escrow

```bash
# Create performance escrow
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows/performance \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "payer": "audit-payer",
    "payee": "audit-payee",
    "amount": "75.00",
    "metric_name": "accuracy",
    "threshold": ">=0.95",
    "description": "Performance gated audit test"
  }' | jq .
# PERF_ESCROW_ID="..."

# Check performance (should be pending — no metrics submitted yet)
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/escrows/$PERF_ESCROW_ID/check-performance \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** Status remains `held` until metrics are submitted and meet threshold.

---

## Phase 4: Identity & Marketplace

### Test 4.1 — Register agent identity

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/identity/agents \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "audit-payer"}' | jq .
```

**Expected:** HTTP 201 with `agent_id`, `created_at`, reputation score.

### Test 4.2 — Check reputation

```bash
curl -s https://sandbox.greenhelix.net/v1/identity/agents/audit-payer/reputation \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

**Expected:** Reputation data returned.

### Test 4.3 — Register marketplace service

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/marketplace/services \
  -H "Authorization: Bearer $PAYEE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_id": "audit-payee",
    "name": "Audit Data Analysis",
    "description": "High-accuracy data analysis for audit testing",
    "category": "data_analysis",
    "tags": ["audit", "test", "analytics"]
  }' | jq .
# SERVICE_ID="..."
```

**Expected:** HTTP 201.

### Test 4.4 — Search and rate service

```bash
# Search
curl -s "https://sandbox.greenhelix.net/v1/marketplace/services?query=audit" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .

# Rate
curl -s -X POST https://sandbox.greenhelix.net/v1/marketplace/services/$SERVICE_ID/ratings \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rating": 5, "review": "Excellent audit test service"}' | jq .

# Best match
curl -s "https://sandbox.greenhelix.net/v1/marketplace/match?query=data+analysis" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

---

## Phase 5: Subscriptions

### Test 5.1 — Create and manage subscription

```bash
# Create subscription
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/subscriptions \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "subscriber": "audit-payer",
    "provider": "audit-payee",
    "amount": "10.00",
    "interval": "monthly",
    "description": "Audit subscription test"
  }' | jq .
# SUB_ID="..."

# Get subscription
curl -s https://sandbox.greenhelix.net/v1/payments/subscriptions/$SUB_ID \
  -H "Authorization: Bearer $PAYER_KEY" | jq .

# List subscriptions
curl -s "https://sandbox.greenhelix.net/v1/payments/subscriptions?agent_id=audit-payer" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .

# Cancel subscription
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/subscriptions/$SUB_ID/cancel \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

---

## Phase 6: Infrastructure & Security

### Test 6.1 — Webhook registration

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/infra/webhooks \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://httpbin.org/post",
    "events": ["payment.captured", "escrow.released"],
    "secret": "webhook-test-secret-123"
  }' | jq .
```

### Test 6.2 — Authentication failures

```bash
# No auth
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents \
  -H "Content-Type: application/json" \
  -d '{"payer":"x","payee":"y","amount":"1.00"}' | jq .
# Expected: 401

# Invalid key
curl -s -X POST https://sandbox.greenhelix.net/v1/payments/intents \
  -H "Authorization: Bearer a2a_free_invalidkey123456789012" \
  -H "Content-Type: application/json" \
  -d '{"payer":"x","payee":"y","amount":"1.00"}' | jq .
# Expected: 401

# Extra fields (extra="forbid")
curl -s -X POST https://sandbox.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test", "unknown_field": "hack"}' | jq .
# Expected: 422
```

### Test 6.3 — Duplicate registration

```bash
curl -s -X POST https://sandbox.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "audit-payer"}' | jq .
# Expected: 409 Conflict
```

### Test 6.4 — Cross-agent access (BOLA)

```bash
# Payee tries to withdraw from payer's wallet
curl -s -X POST https://sandbox.greenhelix.net/v1/billing/wallets/audit-payer/withdraw \
  -H "Authorization: Bearer $PAYEE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "10.00"}' | jq .
# Expected: 403
```

---

## Phase 7: End-to-End Workflow

Run this complete workflow to verify the full payment lifecycle:

```bash
#!/bin/bash
# End-to-end audit test
BASE="https://sandbox.greenhelix.net"

echo "=== 1. Register agents ==="
PAYER=$(curl -s -X POST $BASE/v1/register -H "Content-Type: application/json" \
  -d '{"agent_id": "e2e-payer-'$RANDOM'"}')
PAYEE=$(curl -s -X POST $BASE/v1/register -H "Content-Type: application/json" \
  -d '{"agent_id": "e2e-payee-'$RANDOM'"}')
PAYER_KEY=$(echo $PAYER | jq -r .api_key)
PAYEE_KEY=$(echo $PAYEE | jq -r .api_key)
PAYER_ID=$(echo $PAYER | jq -r .agent_id)
PAYEE_ID=$(echo $PAYEE | jq -r .agent_id)
echo "Payer: $PAYER_ID (key: ${PAYER_KEY:0:20}...)"
echo "Payee: $PAYEE_ID (key: ${PAYEE_KEY:0:20}...)"

echo -e "\n=== 2. Check initial balances ==="
curl -s $BASE/v1/billing/wallets/$PAYER_ID/balance -H "Authorization: Bearer $PAYER_KEY" | jq .balance
curl -s $BASE/v1/billing/wallets/$PAYEE_ID/balance -H "Authorization: Bearer $PAYEE_KEY" | jq .balance

echo -e "\n=== 3. Create payment intent (50 credits) ==="
INTENT=$(curl -s -X POST $BASE/v1/payments/intents \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PAYER_ID\", \"payee\": \"$PAYEE_ID\", \"amount\": \"50.00\", \"description\": \"E2E audit test\"}")
INTENT_ID=$(echo $INTENT | jq -r .id)
echo "Intent: $INTENT_ID (status: $(echo $INTENT | jq -r .status))"

echo -e "\n=== 4. Capture payment ==="
curl -s -X POST $BASE/v1/payments/intents/$INTENT_ID/capture \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status, settlement_amount}'

echo -e "\n=== 5. Verify balances after capture ==="
echo "Payer:"
curl -s $BASE/v1/billing/wallets/$PAYER_ID/balance -H "Authorization: Bearer $PAYER_KEY" | jq .balance
echo "Payee:"
curl -s $BASE/v1/billing/wallets/$PAYEE_ID/balance -H "Authorization: Bearer $PAYEE_KEY" | jq .balance

echo -e "\n=== 6. Create escrow (30 credits) ==="
ESCROW=$(curl -s -X POST $BASE/v1/payments/escrows \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PAYER_ID\", \"payee\": \"$PAYEE_ID\", \"amount\": \"30.00\"}")
ESCROW_ID=$(echo $ESCROW | jq -r .id)
echo "Escrow: $ESCROW_ID (status: $(echo $ESCROW | jq -r .status))"

echo -e "\n=== 7. Release escrow ==="
curl -s -X POST $BASE/v1/payments/escrows/$ESCROW_ID/release \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'

echo -e "\n=== 8. Final balances ==="
echo "Payer (expected: 500 - 50 - 30 = 420):"
curl -s $BASE/v1/billing/wallets/$PAYER_ID/balance -H "Authorization: Bearer $PAYER_KEY" | jq .balance
echo "Payee (expected: 500 + 50 + 30 = 580):"
curl -s $BASE/v1/billing/wallets/$PAYEE_ID/balance -H "Authorization: Bearer $PAYEE_KEY" | jq .balance

echo -e "\n=== 9. Transaction history ==="
curl -s "$BASE/v1/billing/wallets/$PAYER_ID/transactions?limit=5" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '.transactions[] | {type, amount, description}'

echo -e "\n=== DONE ==="
```

---

## For AI Auditor Agent

If you are an AI agent performing this audit, use the Python SDK:

```python
import asyncio
from a2a_client import A2AClient

BASE = "https://sandbox.greenhelix.net"

async def audit():
    results = []

    # Phase 0: Register
    async with A2AClient(BASE) as anon:
        payer_reg = await anon.register_agent(f"audit-payer-{id(anon)}")
        payee_reg = await anon.register_agent(f"audit-payee-{id(anon)}")

    payer_key = payer_reg["api_key"]
    payee_key = payee_reg["api_key"]
    payer_id = payer_reg["agent_id"]
    payee_id = payee_reg["agent_id"]

    async with A2AClient(BASE, api_key=payer_key) as payer, \
               A2AClient(BASE, api_key=payee_key) as payee:

        # Phase 1: Wallet ops
        bal = await payer.get_balance(payer_id)
        assert bal == 500.0, f"Signup bonus expected 500, got {bal}"
        results.append(("signup_bonus", "PASS"))

        await payer.deposit(payer_id, 100.0)
        bal = await payer.get_balance(payer_id)
        assert bal == 600.0, f"Deposit expected 600, got {bal}"
        results.append(("deposit", "PASS"))

        # Phase 2: Payment intent
        intent = await payer.create_payment_intent(
            payer=payer_id, payee=payee_id, amount=50.0,
            memo="Audit payment",
        )
        results.append(("create_intent", "PASS"))

        settlement = await payer.capture_payment(intent["intent_id"])
        results.append(("capture_intent", "PASS"))

        payer_bal = await payer.get_balance(payer_id)
        payee_bal = await payee.get_balance(payee_id)
        assert payer_bal == 550.0, f"Payer expected 550, got {payer_bal}"
        assert payee_bal == 550.0, f"Payee expected 550, got {payee_bal}"
        results.append(("balance_after_capture", "PASS"))

        # Phase 3: Escrow
        escrow = await payer.create_escrow(
            payer=payer_id, payee=payee_id, amount=30.0,
        )
        results.append(("create_escrow", "PASS"))

        await payer.release_escrow(escrow["escrow_id"])
        results.append(("release_escrow", "PASS"))

        payer_bal = await payer.get_balance(payer_id)
        payee_bal = await payee.get_balance(payee_id)
        assert payer_bal == 520.0, f"Payer expected 520, got {payer_bal}"
        assert payee_bal == 580.0, f"Payee expected 580, got {payee_bal}"
        results.append(("balance_after_escrow", "PASS"))

        # Phase 4: Refund
        intent2 = await payer.create_payment_intent(
            payer=payer_id, payee=payee_id, amount=20.0,
        )
        await payer.capture_payment(intent2["intent_id"])
        # Refund it
        refund = await payer.execute("refund_intent", intent_id=intent2["intent_id"])
        results.append(("refund", "PASS"))

        # Phase 5: Marketplace
        svc = await payee.execute(
            "register_service",
            provider_id=payee_id,
            name="Audit Service",
            description="Test service for audit",
            category="testing",
        )
        results.append(("register_service", "PASS"))

        search = await payer.search_services(query="audit")
        results.append(("search_services", "PASS"))

    # Report
    print("\n=== AUDIT RESULTS ===")
    for test, status in results:
        print(f"  [{status}] {test}")
    failures = [t for t, s in results if s != "PASS"]
    if failures:
        print(f"\nFAILED: {failures}")
    else:
        print(f"\nAll {len(results)} tests PASSED.")

asyncio.run(audit())
```

---

## Checklist

### Wallet & Billing
- [ ] Registration creates wallet with 500 credit signup bonus
- [ ] Deposit increases balance correctly
- [ ] Idempotent deposits don't double-credit
- [ ] Withdraw decreases balance correctly
- [ ] Withdraw > balance returns error (402/400)
- [ ] Zero/negative amounts return 422
- [ ] Transaction history lists all operations
- [ ] Budget caps can be set and queried

### Payment Intents
- [ ] Create intent returns status=pending
- [ ] Capture moves funds from payer to payee
- [ ] Balance math is correct after capture (payer -, payee +)
- [ ] Partial capture settles partial amount
- [ ] Refund reverses the payment
- [ ] Non-owner cannot capture (403)
- [ ] Double-capture is rejected

### Escrow
- [ ] Create escrow locks funds (payer balance decreases)
- [ ] Release moves funds to payee
- [ ] Cancel returns funds to payer
- [ ] Payee cannot cancel (403, BOLA)
- [ ] Performance escrow checks metric threshold

### Subscriptions
- [ ] Create subscription succeeds
- [ ] List returns active subscriptions
- [ ] Cancel sets status to cancelled
- [ ] Reactivate restores cancelled subscription

### Marketplace
- [ ] Register service succeeds
- [ ] Search returns matching services
- [ ] Rating (1-5) is saved and returned
- [ ] Best match ranks by trust/price/rating

### Security
- [ ] No auth → 401
- [ ] Invalid key → 401
- [ ] Unknown fields → 422 (extra="forbid")
- [ ] Duplicate registration → 409
- [ ] Cross-agent wallet access → 403

### Stripe Checkout (if Stripe test keys configured)
- [ ] POST /v1/checkout returns Stripe URL
- [ ] Webhook signature validation works
- [ ] Credits deposited after successful checkout
- [ ] Duplicate webhook doesn't double-deposit
