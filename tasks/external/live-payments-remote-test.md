# Live Payments Testing — Remote Machine / Different Network

**Target:** A2A Commerce Platform (Production)
**URL:** `https://api.greenhelix.net`
**Date:** 2026-04-03
**Scope:** Real-world payment correctness from a different machine, network, and geographic location
**Budget:** Max $20 USD equivalent in credits

---

## Purpose

This test validates that all payment flows work correctly when accessed from:
- A **different physical machine** (not the development server)
- A **different network** (different ISP, IP range)
- A **different geographic location** (tests Cloudflare edge routing, TLS, latency)

All tests use **production** (`api.greenhelix.net`) with **real wallets** and **small amounts** (max 20 credits per operation, total budget ≤ 500 credits from signup bonus).

---

## Prerequisites

### For Humans
```bash
# Required tools
which curl jq python3 || echo "Install: curl, jq, python3"

# Verify you're on a different network from the dev server
curl -s https://ifconfig.me
# Should NOT be the same IP as the development server

# Verify TLS and Cloudflare edge
curl -sI https://api.greenhelix.net/v1/health | grep -E "^(cf-ray|server|x-)"
# Expect: cf-ray header (Cloudflare), server: cloudflare
```

### For AI Agents
```bash
pip install httpx  # Only dependency needed (stdlib + httpx)
```

---

## Phase 0: Registration & Environment Validation

### Test 0.1 — Verify production reachability
```bash
BASE="https://api.greenhelix.net"

# Health check
curl -sf -m 10 "$BASE/v1/health" | jq '{status, version, tools}'
# Expected: {"status": "ok", "version": "0.9.1", "tools": 128}

# Verify Cloudflare headers (confirms you're hitting the CDN)
curl -sI "$BASE/v1/health" | grep -i "cf-ray"
# Expected: cf-ray: <hex>-<POP> (POP = 3-letter airport code of nearest edge)

# Check your IP (for geo verification)
echo "Testing from IP: $(curl -s https://ifconfig.me)"
```

### Test 0.2 — Register two test agents
```bash
TIMESTAMP=$(date +%s)

# Agent A (payer) — will send payments
PAYER_REG=$(curl -sf -X POST "$BASE/v1/register" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"remote-payer-$TIMESTAMP\"}")
echo "$PAYER_REG" | jq .

PAYER_KEY=$(echo "$PAYER_REG" | jq -r .api_key)
PAYER_ID=$(echo "$PAYER_REG" | jq -r .agent_id)

# Agent B (payee) — will receive payments
PAYEE_REG=$(curl -sf -X POST "$BASE/v1/register" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"remote-payee-$TIMESTAMP\"}")
echo "$PAYEE_REG" | jq .

PAYEE_KEY=$(echo "$PAYEE_REG" | jq -r .api_key)
PAYEE_ID=$(echo "$PAYEE_REG" | jq -r .agent_id)

echo "Payer: $PAYER_ID → key ${PAYER_KEY:0:20}..."
echo "Payee: $PAYEE_ID → key ${PAYEE_KEY:0:20}..."
```

**Expected:** Each agent gets HTTP 201, tier=free, balance=500.0 credits.

### Test 0.3 — Verify initial balances
```bash
curl -sf "$BASE/v1/billing/wallets/$PAYER_ID/balance" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
curl -sf "$BASE/v1/billing/wallets/$PAYEE_ID/balance" \
  -H "Authorization: Bearer $PAYEE_KEY" | jq .
```

**Expected:** Both show `{"agent_id": "...", "balance": 500.0, "currency": "CREDITS"}`

---

## Phase 1: Wallet Operations (Real Credits)

### Test 1.1 — Deposit 10 credits
```bash
curl -sf -X POST "$BASE/v1/billing/wallets/$PAYER_ID/deposit" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "10.00"}' | jq '{balance, transaction_id}'
```
**Expected:** balance=510.0, returns transaction_id.

### Test 1.2 — Idempotent deposit (no double-credit)
```bash
IDEMP_KEY="remote-deposit-$(date +%s)"

curl -sf -X POST "$BASE/v1/billing/wallets/$PAYER_ID/deposit" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEMP_KEY" \
  -d '{"amount": "5.00"}' | jq '{balance, transaction_id}'

# Repeat identical request
FIRST_TXN=$(curl -sf -X POST "$BASE/v1/billing/wallets/$PAYER_ID/deposit" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $IDEMP_KEY" \
  -d '{"amount": "5.00"}' | jq -r .transaction_id)

echo "Second call returned same txn: $FIRST_TXN"
```
**Expected:** Balance increases by 5 only once (515.0 total). Same transaction_id both times.

### Test 1.3 — Withdraw 3 credits
```bash
curl -sf -X POST "$BASE/v1/billing/wallets/$PAYER_ID/withdraw" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "3.00"}' | jq '{balance}'
```
**Expected:** balance=512.0.

### Test 1.4 — Overdraft protection
```bash
curl -s -X POST "$BASE/v1/billing/wallets/$PAYER_ID/withdraw" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "99999.00"}' | jq '{status, detail}'
```
**Expected:** HTTP 402 or 400 — insufficient funds.

### Test 1.5 — Invalid amounts rejected
```bash
# Zero
curl -s -X POST "$BASE/v1/billing/wallets/$PAYER_ID/deposit" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "0"}' | jq '{status, detail}'

# Negative
curl -s -X POST "$BASE/v1/billing/wallets/$PAYER_ID/deposit" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "-5.00"}' | jq '{status, detail}'
```
**Expected:** HTTP 422 for both (Pydantic: `amount` must be `gt=0`).

### Test 1.6 — Transaction history
```bash
curl -sf "$BASE/v1/billing/wallets/$PAYER_ID/transactions?limit=10" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '.transactions[] | {type, amount, description}'
```
**Expected:** Lists signup_bonus, deposit(s), withdraw in chronological order.

### Test 1.7 — Budget caps
```bash
curl -sf -X PUT "$BASE/v1/billing/wallets/$PAYER_ID/budget" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"daily_cap": "50.00", "monthly_cap": "200.00"}' | jq .

curl -sf "$BASE/v1/billing/wallets/$PAYER_ID/budget" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```
**Expected:** Caps saved and returned correctly.

---

## Phase 2: Payment Intents — Full Lifecycle

### Test 2.1 — Create payment intent (15 credits)
```bash
INTENT_RES=$(curl -sf -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"payer\": \"$PAYER_ID\",
    \"payee\": \"$PAYEE_ID\",
    \"amount\": \"15.00\",
    \"description\": \"Remote live payment test\"
  }")
echo "$INTENT_RES" | jq .
INTENT_ID=$(echo "$INTENT_RES" | jq -r .id)
echo "Intent ID: $INTENT_ID"
```
**Expected:** HTTP 201, status=pending. Payer balance NOT yet deducted.

### Test 2.2 — Capture payment
```bash
curl -sf -X POST "$BASE/v1/payments/intents/$INTENT_ID/capture" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status, settlement_amount}'
```
**Expected:** status=captured. Payer -15, payee +15.

### Test 2.3 — Verify balance transfer
```bash
echo "Payer balance:"
curl -sf "$BASE/v1/billing/wallets/$PAYER_ID/balance" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .balance
echo "Payee balance:"
curl -sf "$BASE/v1/billing/wallets/$PAYEE_ID/balance" \
  -H "Authorization: Bearer $PAYEE_KEY" | jq .balance
```
**Expected:** Payer ~497.0 (512 - 15), Payee 515.0 (500 + 15).

### Test 2.4 — Refund captured payment
```bash
curl -sf -X POST "$BASE/v1/payments/intents/$INTENT_ID/refund" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'
```
**Expected:** status=refunded. Funds returned to payer.

### Test 2.5 — Partial capture (20 → capture 8)
```bash
INTENT2_RES=$(curl -sf -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PAYER_ID\", \"payee\": \"$PAYEE_ID\", \"amount\": \"20.00\"}")
INTENT2_ID=$(echo "$INTENT2_RES" | jq -r .id)

curl -sf -X POST "$BASE/v1/payments/intents/$INTENT2_ID/partial-capture" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "8.00"}' | jq '{status, settlement_amount}'
```
**Expected:** Settlement for 8.0 credits. Remaining 12.0 released.

### Test 2.6 — Non-owner cannot capture (BOLA)
```bash
INTENT3_RES=$(curl -sf -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PAYER_ID\", \"payee\": \"$PAYEE_ID\", \"amount\": \"5.00\"}")
INTENT3_ID=$(echo "$INTENT3_RES" | jq -r .id)

# Payee tries to capture — should fail
curl -s -X POST "$BASE/v1/payments/intents/$INTENT3_ID/capture" \
  -H "Authorization: Bearer $PAYEE_KEY" | jq '{status, detail}'
```
**Expected:** HTTP 403 — only payer or admin can capture.

### Test 2.7 — Double-capture rejected
```bash
# First capture (succeeds)
curl -sf -X POST "$BASE/v1/payments/intents/$INTENT3_ID/capture" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'

# Second capture (should fail)
curl -s -X POST "$BASE/v1/payments/intents/$INTENT3_ID/capture" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status, detail}'
```
**Expected:** First returns captured. Second returns error (already captured).

---

## Phase 3: Escrow — Hold, Release, Cancel

### Test 3.1 — Create and release escrow (10 credits)
```bash
ESCROW_RES=$(curl -sf -X POST "$BASE/v1/payments/escrows" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"payer\": \"$PAYER_ID\",
    \"payee\": \"$PAYEE_ID\",
    \"amount\": \"10.00\",
    \"description\": \"Remote escrow test\"
  }")
echo "$ESCROW_RES" | jq .
ESCROW_ID=$(echo "$ESCROW_RES" | jq -r .id)
```
**Expected:** HTTP 201, status=held. Payer balance decreases by 10.

```bash
curl -sf -X POST "$BASE/v1/payments/escrows/$ESCROW_ID/release" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'
```
**Expected:** status=released. Payee balance increases by 10.

### Test 3.2 — Create and cancel escrow (8 credits)
```bash
ESCROW2_RES=$(curl -sf -X POST "$BASE/v1/payments/escrows" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PAYER_ID\", \"payee\": \"$PAYEE_ID\", \"amount\": \"8.00\"}")
ESCROW2_ID=$(echo "$ESCROW2_RES" | jq -r .id)

curl -sf -X POST "$BASE/v1/payments/escrows/$ESCROW2_ID/cancel" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'
```
**Expected:** status=cancelled. Funds returned to payer.

### Test 3.3 — Payee cannot cancel (BOLA)
```bash
ESCROW3_RES=$(curl -sf -X POST "$BASE/v1/payments/escrows" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PAYER_ID\", \"payee\": \"$PAYEE_ID\", \"amount\": \"5.00\"}")
ESCROW3_ID=$(echo "$ESCROW3_RES" | jq -r .id)

# Payee tries to cancel — must fail
curl -s -X POST "$BASE/v1/payments/escrows/$ESCROW3_ID/cancel" \
  -H "Authorization: Bearer $PAYEE_KEY" | jq '{status, detail}'
```
**Expected:** HTTP 403 — only payer can cancel.

```bash
# Clean up: payer cancels it
curl -sf -X POST "$BASE/v1/payments/escrows/$ESCROW3_ID/cancel" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'
```

---

## Phase 4: Identity & Marketplace

### Test 4.1 — Register identity
```bash
curl -sf -X POST "$BASE/v1/identity/agents" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"$PAYER_ID\"}" | jq .
```
**Expected:** HTTP 201 with agent identity record.

### Test 4.2 — Check reputation
```bash
curl -sf "$BASE/v1/identity/agents/$PAYER_ID/reputation" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

### Test 4.3 — Register marketplace service
```bash
SVC_RES=$(curl -sf -X POST "$BASE/v1/marketplace/services" \
  -H "Authorization: Bearer $PAYEE_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"provider_id\": \"$PAYEE_ID\",
    \"name\": \"Remote Test Service\",
    \"description\": \"Service registered from remote location for testing\",
    \"category\": \"testing\",
    \"tags\": [\"remote\", \"live-test\"]
  }")
echo "$SVC_RES" | jq .
SERVICE_ID=$(echo "$SVC_RES" | jq -r .id)
```

### Test 4.4 — Search and rate
```bash
curl -sf "$BASE/v1/marketplace/services?query=remote" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '.[] | {name, provider_id}'

curl -sf -X POST "$BASE/v1/marketplace/services/$SERVICE_ID/ratings" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"rating": 4, "review": "Good service, tested from remote location"}' | jq .

curl -sf "$BASE/v1/marketplace/match?query=testing" \
  -H "Authorization: Bearer $PAYER_KEY" | jq .
```

---

## Phase 5: Subscriptions

### Test 5.1 — Full subscription lifecycle (5 credits/month)
```bash
SUB_RES=$(curl -sf -X POST "$BASE/v1/payments/subscriptions" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"subscriber\": \"$PAYER_ID\",
    \"provider\": \"$PAYEE_ID\",
    \"amount\": \"5.00\",
    \"interval\": \"monthly\",
    \"description\": \"Remote subscription test\"
  }")
echo "$SUB_RES" | jq .
SUB_ID=$(echo "$SUB_RES" | jq -r .id)

# List
curl -sf "$BASE/v1/payments/subscriptions?agent_id=$PAYER_ID" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '.[] | {id, status, amount}'

# Cancel
curl -sf -X POST "$BASE/v1/payments/subscriptions/$SUB_ID/cancel" \
  -H "Authorization: Bearer $PAYER_KEY" | jq '{status}'
```
**Expected:** Create → active, list shows it, cancel → cancelled.

---

## Phase 6: Security (from Remote Network)

These tests are especially valuable from a different network — they validate Cloudflare edge behavior and IP-based security.

### Test 6.1 — No auth
```bash
curl -s -X POST "$BASE/v1/payments/intents" \
  -H "Content-Type: application/json" \
  -d '{"payer":"x","payee":"y","amount":"1.00"}' | jq '{status, detail}'
```
**Expected:** HTTP 401.

### Test 6.2 — Invalid key
```bash
curl -s -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer a2a_free_000000000000000000000000" \
  -H "Content-Type: application/json" \
  -d '{"payer":"x","payee":"y","amount":"1.00"}' | jq '{status, detail}'
```
**Expected:** HTTP 401.

### Test 6.3 — Extra fields rejected
```bash
curl -s -X POST "$BASE/v1/register" \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test-extra", "unknown_field": "hack"}' | jq '{status, detail}'
```
**Expected:** HTTP 422 (Pydantic extra="forbid").

### Test 6.4 — Cross-agent wallet access (BOLA)
```bash
curl -s -X POST "$BASE/v1/billing/wallets/$PAYER_ID/withdraw" \
  -H "Authorization: Bearer $PAYEE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"amount": "1.00"}' | jq '{status, detail}'
```
**Expected:** HTTP 403 — payee cannot access payer's wallet.

### Test 6.5 — Duplicate registration
```bash
curl -s -X POST "$BASE/v1/register" \
  -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"$PAYER_ID\"}" | jq '{status, detail}'
```
**Expected:** HTTP 409 Conflict.

### Test 6.6 — Response headers check
```bash
curl -sI "$BASE/v1/health" | grep -iE "^(x-content|x-frame|strict|content-security|referrer|permissions|x-request)"
```
**Expected:** Security headers present (HSTS, X-Frame-Options: DENY, CSP, etc.).

### Test 6.7 — Latency from this location
```bash
for i in $(seq 1 5); do
  START=$(date +%s%N)
  curl -sf -o /dev/null "$BASE/v1/health"
  END=$(date +%s%N)
  echo "Request $i: $(( (END - START) / 1000000 ))ms"
done
```
**Expected:** Records baseline latency from this geographic location.

---

## Phase 7: End-to-End Script

Copy and run this complete script on the remote machine:

```bash
#!/bin/bash
set -euo pipefail

BASE="https://api.greenhelix.net"
TS=$(date +%s)
PASS=0; FAIL=0; TOTAL=0

check() {
  TOTAL=$((TOTAL + 1))
  if [ "$1" = "true" ]; then
    PASS=$((PASS + 1))
    echo "  [PASS] $2"
  else
    FAIL=$((FAIL + 1))
    echo "  [FAIL] $2"
  fi
}

echo "=== A2A Live Payment Test — Remote Machine ==="
echo "Date: $(date -u)"
echo "IP: $(curl -s https://ifconfig.me)"
echo "Target: $BASE"
echo ""

echo "--- Phase 0: Setup ---"
PAYER=$(curl -sf -X POST "$BASE/v1/register" -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"e2e-remote-payer-$TS\"}")
PAYEE=$(curl -sf -X POST "$BASE/v1/register" -H "Content-Type: application/json" \
  -d "{\"agent_id\": \"e2e-remote-payee-$TS\"}")
PK=$(echo "$PAYER" | jq -r .api_key)
YK=$(echo "$PAYEE" | jq -r .api_key)
PI=$(echo "$PAYER" | jq -r .agent_id)
YI=$(echo "$PAYEE" | jq -r .agent_id)
PB=$(echo "$PAYER" | jq -r .balance)
check "$([ "$PB" = "500" ] && echo true || echo false)" "Signup bonus = 500"

echo ""
echo "--- Phase 1: Wallet ---"
DEP=$(curl -sf -X POST "$BASE/v1/billing/wallets/$PI/deposit" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d '{"amount": "10.00"}')
BAL=$(echo "$DEP" | jq -r .balance)
check "$([ "$BAL" = "510.0" ] && echo true || echo false)" "Deposit 10 → balance 510"

WD=$(curl -sf -X POST "$BASE/v1/billing/wallets/$PI/withdraw" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d '{"amount": "5.00"}')
BAL=$(echo "$WD" | jq -r .balance)
check "$([ "$BAL" = "505.0" ] && echo true || echo false)" "Withdraw 5 → balance 505"

OD_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/billing/wallets/$PI/withdraw" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d '{"amount": "99999.00"}')
check "$([ "$OD_STATUS" = "402" ] || [ "$OD_STATUS" = "400" ] && echo true || echo false)" "Overdraft rejected ($OD_STATUS)"

ZERO_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/billing/wallets/$PI/deposit" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d '{"amount": "0"}')
check "$([ "$ZERO_STATUS" = "422" ] && echo true || echo false)" "Zero amount rejected ($ZERO_STATUS)"

echo ""
echo "--- Phase 2: Payment Intent ---"
INTENT=$(curl -sf -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PI\", \"payee\": \"$YI\", \"amount\": \"15.00\", \"description\": \"E2E remote test\"}")
IID=$(echo "$INTENT" | jq -r .id)
ISTATUS=$(echo "$INTENT" | jq -r .status)
check "$([ "$ISTATUS" = "pending" ] && echo true || echo false)" "Intent created (status=$ISTATUS)"

CAP=$(curl -sf -X POST "$BASE/v1/payments/intents/$IID/capture" \
  -H "Authorization: Bearer $PK")
CSTATUS=$(echo "$CAP" | jq -r .status)
check "$([ "$CSTATUS" = "captured" ] && echo true || echo false)" "Intent captured (status=$CSTATUS)"

PBAL=$(curl -sf "$BASE/v1/billing/wallets/$PI/balance" -H "Authorization: Bearer $PK" | jq -r .balance)
YBAL=$(curl -sf "$BASE/v1/billing/wallets/$YI/balance" -H "Authorization: Bearer $YK" | jq -r .balance)
echo "  Payer balance: $PBAL, Payee balance: $YBAL"

REF=$(curl -sf -X POST "$BASE/v1/payments/intents/$IID/refund" -H "Authorization: Bearer $PK")
RSTATUS=$(echo "$REF" | jq -r .status)
check "$([ "$RSTATUS" = "refunded" ] && echo true || echo false)" "Intent refunded (status=$RSTATUS)"

# Non-owner capture
INTENT2=$(curl -sf -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PI\", \"payee\": \"$YI\", \"amount\": \"5.00\"}")
IID2=$(echo "$INTENT2" | jq -r .id)
BOLA_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/payments/intents/$IID2/capture" \
  -H "Authorization: Bearer $YK")
check "$([ "$BOLA_STATUS" = "403" ] && echo true || echo false)" "Non-owner capture blocked ($BOLA_STATUS)"

echo ""
echo "--- Phase 3: Escrow ---"
ESCROW=$(curl -sf -X POST "$BASE/v1/payments/escrows" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PI\", \"payee\": \"$YI\", \"amount\": \"10.00\", \"description\": \"Remote escrow\"}")
EID=$(echo "$ESCROW" | jq -r .id)
ESTATUS=$(echo "$ESCROW" | jq -r .status)
check "$([ "$ESTATUS" = "held" ] && echo true || echo false)" "Escrow created (status=$ESTATUS)"

REL=$(curl -sf -X POST "$BASE/v1/payments/escrows/$EID/release" -H "Authorization: Bearer $PK")
RELSTATUS=$(echo "$REL" | jq -r .status)
check "$([ "$RELSTATUS" = "released" ] && echo true || echo false)" "Escrow released (status=$RELSTATUS)"

ESCROW2=$(curl -sf -X POST "$BASE/v1/payments/escrows" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PI\", \"payee\": \"$YI\", \"amount\": \"8.00\"}")
EID2=$(echo "$ESCROW2" | jq -r .id)
CAN=$(curl -sf -X POST "$BASE/v1/payments/escrows/$EID2/cancel" -H "Authorization: Bearer $PK")
CANSTATUS=$(echo "$CAN" | jq -r .status)
check "$([ "$CANSTATUS" = "cancelled" ] && echo true || echo false)" "Escrow cancelled (status=$CANSTATUS)"

# Payee cancel BOLA
ESCROW3=$(curl -sf -X POST "$BASE/v1/payments/escrows" \
  -H "Authorization: Bearer $PK" -H "Content-Type: application/json" \
  -d "{\"payer\": \"$PI\", \"payee\": \"$YI\", \"amount\": \"5.00\"}")
EID3=$(echo "$ESCROW3" | jq -r .id)
BOLA2=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/payments/escrows/$EID3/cancel" \
  -H "Authorization: Bearer $YK")
check "$([ "$BOLA2" = "403" ] && echo true || echo false)" "Payee cancel blocked ($BOLA2)"
# Cleanup
curl -sf -X POST "$BASE/v1/payments/escrows/$EID3/cancel" -H "Authorization: Bearer $PK" > /dev/null

echo ""
echo "--- Phase 4: Security ---"
NOAUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/payments/intents" \
  -H "Content-Type: application/json" -d '{"payer":"x","payee":"y","amount":"1.00"}')
check "$([ "$NOAUTH" = "401" ] && echo true || echo false)" "No auth → $NOAUTH"

BADKEY=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/payments/intents" \
  -H "Authorization: Bearer a2a_free_000000000000000000000000" \
  -H "Content-Type: application/json" -d '{"payer":"x","payee":"y","amount":"1.00"}')
check "$([ "$BADKEY" = "401" ] && echo true || echo false)" "Bad key → $BADKEY"

EXTRA=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/register" \
  -H "Content-Type: application/json" -d '{"agent_id":"xtra-test","unknown":"hack"}')
check "$([ "$EXTRA" = "422" ] && echo true || echo false)" "Extra fields → $EXTRA"

CROSS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/v1/billing/wallets/$PI/withdraw" \
  -H "Authorization: Bearer $YK" -H "Content-Type: application/json" -d '{"amount":"1.00"}')
check "$([ "$CROSS" = "403" ] && echo true || echo false)" "Cross-agent access → $CROSS"

echo ""
echo "--- Phase 5: Final Balances ---"
echo "Payer ($PI):"
curl -sf "$BASE/v1/billing/wallets/$PI/balance" -H "Authorization: Bearer $PK" | jq .balance
echo "Payee ($YI):"
curl -sf "$BASE/v1/billing/wallets/$YI/balance" -H "Authorization: Bearer $YK" | jq .balance

echo ""
echo "========================================="
echo "Results: $PASS/$TOTAL passed, $FAIL failed"
if [ "$FAIL" -eq 0 ]; then
  echo "STATUS: ALL PASS"
else
  echo "STATUS: $FAIL FAILURES"
fi
echo "========================================="
```

---

## For AI Auditor Agent

If you are an AI agent running this audit, use this Python script. It requires only `httpx` (no SDK needed).

```python
#!/usr/bin/env python3
"""
A2A Live Payment Audit — Remote Machine
Run from a different machine/network/geo to validate real-world payments.
Target: https://api.greenhelix.net (production, real credits)
Budget: max 500 credits (from signup bonus, no real USD spent)
"""

import asyncio
import time

import httpx

BASE = "https://api.greenhelix.net"


async def audit():
    results = []
    ts = int(time.time())

    async with httpx.AsyncClient(base_url=BASE, timeout=30.0, follow_redirects=True) as c:

        # --- Phase 0: Registration ---
        payer = (await c.post("/v1/register", json={"agent_id": f"ai-remote-payer-{ts}"})).json()
        payee = (await c.post("/v1/register", json={"agent_id": f"ai-remote-payee-{ts}"})).json()
        pk, yk = payer["api_key"], payee["api_key"]
        pi, yi = payer["agent_id"], payee["agent_id"]
        ph = {"Authorization": f"Bearer {pk}"}
        yh = {"Authorization": f"Bearer {yk}"}

        assert payer["balance"] == 500.0, f"Signup bonus: {payer['balance']}"
        results.append(("registration", "PASS"))

        # --- Phase 1: Wallet ---
        r = (await c.post(f"/v1/billing/wallets/{pi}/deposit", json={"amount": "10.00"}, headers=ph)).json()
        assert r["balance"] == 510.0, f"Deposit: {r['balance']}"
        results.append(("deposit", "PASS"))

        r = (await c.post(f"/v1/billing/wallets/{pi}/withdraw", json={"amount": "3.00"}, headers=ph)).json()
        assert r["balance"] == 507.0, f"Withdraw: {r['balance']}"
        results.append(("withdraw", "PASS"))

        r = await c.post(f"/v1/billing/wallets/{pi}/withdraw", json={"amount": "99999"}, headers=ph)
        assert r.status_code in (400, 402), f"Overdraft: {r.status_code}"
        results.append(("overdraft_protection", "PASS"))

        r = await c.post(f"/v1/billing/wallets/{pi}/deposit", json={"amount": "0"}, headers=ph)
        assert r.status_code == 422, f"Zero amount: {r.status_code}"
        r = await c.post(f"/v1/billing/wallets/{pi}/deposit", json={"amount": "-5"}, headers=ph)
        assert r.status_code == 422, f"Negative amount: {r.status_code}"
        results.append(("invalid_amounts", "PASS"))

        # Idempotency
        idemp = {"Idempotency-Key": f"ai-idemp-{ts}"}
        r1 = (await c.post(f"/v1/billing/wallets/{pi}/deposit", json={"amount": "5.00"}, headers={**ph, **idemp})).json()
        r2 = (await c.post(f"/v1/billing/wallets/{pi}/deposit", json={"amount": "5.00"}, headers={**ph, **idemp})).json()
        assert r1.get("transaction_id") == r2.get("transaction_id"), "Idempotency failed"
        results.append(("idempotency", "PASS"))

        # --- Phase 2: Payment Intents ---
        intent = (await c.post("/v1/payments/intents", json={
            "payer": pi, "payee": yi, "amount": "15.00", "description": "AI remote test"
        }, headers=ph)).json()
        iid = intent["id"]
        assert intent["status"] == "pending", f"Intent status: {intent['status']}"
        results.append(("create_intent", "PASS"))

        cap = (await c.post(f"/v1/payments/intents/{iid}/capture", headers=ph)).json()
        assert cap["status"] == "captured", f"Capture: {cap['status']}"
        results.append(("capture_intent", "PASS"))

        pb = (await c.get(f"/v1/billing/wallets/{pi}/balance", headers=ph)).json()["balance"]
        yb = (await c.get(f"/v1/billing/wallets/{yi}/balance", headers=yh)).json()["balance"]
        assert yb == 515.0, f"Payee balance: {yb}"
        results.append(("balance_transfer", "PASS"))

        ref = (await c.post(f"/v1/payments/intents/{iid}/refund", headers=ph)).json()
        assert ref["status"] == "refunded", f"Refund: {ref['status']}"
        results.append(("refund", "PASS"))

        # BOLA: payee can't capture
        i2 = (await c.post("/v1/payments/intents", json={
            "payer": pi, "payee": yi, "amount": "5.00"
        }, headers=ph)).json()
        bola = await c.post(f"/v1/payments/intents/{i2['id']}/capture", headers=yh)
        assert bola.status_code == 403, f"BOLA capture: {bola.status_code}"
        results.append(("bola_capture", "PASS"))

        # --- Phase 3: Escrow ---
        esc = (await c.post("/v1/payments/escrows", json={
            "payer": pi, "payee": yi, "amount": "10.00", "description": "AI escrow"
        }, headers=ph)).json()
        assert esc["status"] == "held", f"Escrow: {esc['status']}"
        results.append(("create_escrow", "PASS"))

        rel = (await c.post(f"/v1/payments/escrows/{esc['id']}/release", headers=ph)).json()
        assert rel["status"] == "released", f"Release: {rel['status']}"
        results.append(("release_escrow", "PASS"))

        esc2 = (await c.post("/v1/payments/escrows", json={
            "payer": pi, "payee": yi, "amount": "8.00"
        }, headers=ph)).json()
        can = (await c.post(f"/v1/payments/escrows/{esc2['id']}/cancel", headers=ph)).json()
        assert can["status"] == "cancelled", f"Cancel: {can['status']}"
        results.append(("cancel_escrow", "PASS"))

        # BOLA: payee can't cancel
        esc3 = (await c.post("/v1/payments/escrows", json={
            "payer": pi, "payee": yi, "amount": "5.00"
        }, headers=ph)).json()
        bola2 = await c.post(f"/v1/payments/escrows/{esc3['id']}/cancel", headers=yh)
        assert bola2.status_code == 403, f"BOLA cancel: {bola2.status_code}"
        await c.post(f"/v1/payments/escrows/{esc3['id']}/cancel", headers=ph)  # cleanup
        results.append(("bola_cancel", "PASS"))

        # --- Phase 4: Marketplace ---
        svc = (await c.post("/v1/marketplace/services", json={
            "provider_id": yi, "name": "AI Remote Service",
            "description": "Test from AI agent", "category": "testing", "tags": ["remote"]
        }, headers=yh)).json()
        results.append(("register_service", "PASS"))

        search = (await c.get("/v1/marketplace/services", params={"query": "remote"}, headers=ph)).json()
        assert len(search) > 0, "No services found"
        results.append(("search_services", "PASS"))

        # --- Phase 5: Security ---
        r = await c.post("/v1/payments/intents", json={"payer": "x", "payee": "y", "amount": "1.00"})
        assert r.status_code == 401, f"No auth: {r.status_code}"
        results.append(("no_auth_401", "PASS"))

        r = await c.post("/v1/payments/intents", json={"payer": "x", "payee": "y", "amount": "1.00"},
                         headers={"Authorization": "Bearer a2a_free_000000000000000000000000"})
        assert r.status_code == 401, f"Bad key: {r.status_code}"
        results.append(("bad_key_401", "PASS"))

        r = await c.post("/v1/register", json={"agent_id": "x", "unknown": "hack"})
        assert r.status_code == 422, f"Extra fields: {r.status_code}"
        results.append(("extra_fields_422", "PASS"))

        r = await c.post(f"/v1/billing/wallets/{pi}/withdraw", json={"amount": "1.00"}, headers=yh)
        assert r.status_code == 403, f"Cross-agent: {r.status_code}"
        results.append(("cross_agent_403", "PASS"))

        # --- Final balances ---
        pb = (await c.get(f"/v1/billing/wallets/{pi}/balance", headers=ph)).json()["balance"]
        yb = (await c.get(f"/v1/billing/wallets/{yi}/balance", headers=yh)).json()["balance"]
        print(f"\nFinal balances: payer={pb}, payee={yb}")

    # --- Report ---
    print("\n=== AUDIT RESULTS ===")
    for name, status in results:
        print(f"  [{status}] {name}")
    failures = [n for n, s in results if s != "PASS"]
    if failures:
        print(f"\nFAILED: {failures}")
    else:
        print(f"\nAll {len(results)} tests PASSED.")
    return len(failures) == 0


if __name__ == "__main__":
    import sys
    ok = asyncio.run(audit())
    sys.exit(0 if ok else 1)
```

---

## Checklist

### Setup & Environment
- [ ] Running from different IP than dev server
- [ ] Running from different network/ISP
- [ ] Cloudflare edge POP visible in cf-ray header
- [ ] TLS 1.3 confirmed
- [ ] Health check returns 200

### Wallet & Billing
- [ ] Registration creates wallet with 500 credit bonus
- [ ] Deposit increases balance correctly
- [ ] Idempotent deposits don't double-credit
- [ ] Withdraw decreases balance correctly
- [ ] Overdraft returns 402/400
- [ ] Zero/negative amounts return 422
- [ ] Transaction history lists all ops
- [ ] Budget caps can be set and queried

### Payment Intents
- [ ] Create intent → status=pending
- [ ] Capture moves funds payer→payee
- [ ] Balance math correct after capture
- [ ] Partial capture settles partial amount
- [ ] Refund reverses the payment
- [ ] Non-owner cannot capture (403)
- [ ] Double-capture rejected

### Escrow
- [ ] Create escrow locks funds (payer balance decreases)
- [ ] Release moves funds to payee
- [ ] Cancel returns funds to payer
- [ ] Payee cannot cancel (403)

### Subscriptions
- [ ] Create subscription → active
- [ ] List returns subscription
- [ ] Cancel → cancelled

### Marketplace
- [ ] Register service succeeds
- [ ] Search returns matching services
- [ ] Rating saved and returned

### Security (from Remote Network)
- [ ] No auth → 401
- [ ] Invalid key → 401
- [ ] Extra fields → 422
- [ ] Duplicate registration → 409
- [ ] Cross-agent access → 403
- [ ] Security headers present
- [ ] Latency from this geo recorded

### Cross-Network Specific
- [ ] All responses parse correctly (no Cloudflare captchas or blocks)
- [ ] No unexpected 5xx errors
- [ ] Latency within acceptable range for geo distance
- [ ] All payment math identical to sandbox results
