# External Audit: Live Payments — Combined Prompt for AI Auditor Agent

**Target:** A2A Commerce Platform
**Version:** Combined prompt (merges `live-payments-audit.md` + `live-payments-remote-test.md`, plus live-money Stripe flows)
**Date:** 2026-04-05

---

## TL;DR for the AI Auditor Agent

You are an independent auditor. Your job is to verify that the A2A Commerce Platform's payments stack works correctly end-to-end against two live environments, and that **real-money (Stripe) deposits correctly credit live wallets**. Run every phase below, record each result, and produce a final report.

You will receive:

1. **Two environment URLs** — `SANDBOX` and `PROD` (see `Environments` table below).
2. **Pre-provisioned credentials** — a bundle from the human operator containing API keys for pre-funded "live wallets" (see `Inputs from human` below).
3. **A Stripe test card** — for live checkout flows (`4242 4242 4242 4242`, any future expiry, any CVC, any ZIP).

You must run **all 8 phases** against BOTH environments unless marked `[SANDBOX-ONLY]` or `[PROD-ONLY]`. Produce a single consolidated audit report as described in `Output format`.

---

## Environments

| Env | Base URL | Stripe Mode | Notes |
|-----|----------|-------------|-------|
| **SANDBOX** | `https://sandbox.greenhelix.net` | Test keys | Fresh DB per deploy. Safe for destructive tests. |
| **PROD** | `https://api.greenhelix.net` | **Live keys** | Real data. Budget-capped. Do not exceed $20 USD total spend. |
| Swagger | `https://sandbox.greenhelix.net/docs` | — | Interactive API browser |
| OpenAPI | `https://sandbox.greenhelix.net/v1/openapi.json` | — | Machine-readable spec |
| Pricing | `https://sandbox.greenhelix.net/v1/pricing` | — | Tool catalog |

All traffic goes through Cloudflare (TLSv1.3). Auth via `Authorization: Bearer <api_key>` or `X-API-Key: <api_key>`.

---

## Inputs from human (the Live-Wallet bundle)

The human operator will deliver a JSON bundle named `live-wallets.json`. Its schema is:

```json
{
  "sandbox": {
    "payer":    {"agent_id": "audit-payer-sbx",    "api_key": "a2a_free_...", "tier": "free",  "initial_balance": 500.0},
    "payee":    {"agent_id": "audit-payee-sbx",    "api_key": "a2a_free_...", "tier": "free",  "initial_balance": 500.0},
    "platform": {"agent_id": "audit-platform-sbx", "api_key": "a2a_free_...", "tier": "free",  "initial_balance": 500.0},
    "pro":      {"agent_id": "audit-pro-sbx",      "api_key": "a2a_pro_...",  "tier": "pro",   "initial_balance": 1000.0}
  },
  "prod": {
    "payer":    {"agent_id": "audit-payer-prod",   "api_key": "a2a_free_...", "tier": "free",  "initial_balance": 500.0, "budget_cap_usd": 10.0},
    "payee":    {"agent_id": "audit-payee-prod",   "api_key": "a2a_free_...", "tier": "free",  "initial_balance": 500.0, "budget_cap_usd": 0.0},
    "platform": {"agent_id": "audit-platform-prod","api_key": "a2a_free_...", "tier": "free",  "initial_balance": 500.0, "budget_cap_usd": 0.0},
    "pro":      {"agent_id": "audit-pro-prod",     "api_key": "a2a_pro_...",  "tier": "pro",   "initial_balance": 500.0, "budget_cap_usd": 10.0}
  },
  "stripe": {
    "test_card":   {"number": "4242 4242 4242 4242", "exp": "12/30", "cvc": "123", "zip": "10001"},
    "declined_card": {"number": "4000 0000 0000 0002", "exp": "12/30", "cvc": "123", "zip": "10001"},
    "3ds_card": {"number": "4000 0025 0000 3155", "exp": "12/30", "cvc": "123", "zip": "10001"}
  },
  "budget": {
    "max_usd_spend": 20.0,
    "max_credits_per_op": 20.0
  }
}
```

If any field is missing, STOP and ask the human to regenerate the bundle.

---

## Phase 0 — Environment validation

Run BOTH env (SANDBOX + PROD):

0.1. `GET /v1/health` — expect `{"status": "ok", ...}` with 200.
0.2. `curl -sI $BASE/v1/health` — expect `cf-ray` header (confirms Cloudflare edge).
0.3. `GET /v1/openapi.json` — expect 200, parse as JSON, verify it contains `/v1/payments/intents` path.
0.4. Record your public IP (`curl -s https://ifconfig.me`) and timestamp — include in final report.
0.5. Verify each provided API key works: `GET /v1/billing/wallets/{agent_id}/balance` — expect 200 with correct `initial_balance` (or record discrepancy).
0.6. Measure baseline latency: 5 calls to `/v1/health`, record mean/min/max/p95.

---

## Phase 1 — Wallet & billing correctness

Run BOTH env. Use the `payer` wallet from the live-wallet bundle. All amounts in credits.

1.1. **Deposit** `10.00` → expect balance += 10.
1.2. **Idempotent deposit** with `Idempotency-Key: audit-dep-<ts>` sent twice → same `transaction_id`, balance += 5 once.
1.3. **Withdraw** `3.00` → expect balance -= 3.
1.4. **Overdraft** `99999.00` → expect HTTP 402 or 400.
1.5. **Zero amount** → expect HTTP 422. **Negative amount** → expect HTTP 422. **String "abc"** → expect HTTP 422.
1.6. `GET /v1/billing/wallets/{id}/transactions?limit=10` → expect list containing your deposit + withdraw ops.
1.7. **Budget caps** `PUT /v1/billing/wallets/{id}/budget {"daily_cap": "50.00", "monthly_cap": "200.00"}` → verify via GET.
1.8. **Transaction types** — verify each transaction has required fields: `id`, `type`, `amount`, `timestamp`, `description`.

---

## Phase 2 — Payment intents (authorize → capture → refund)

Run BOTH env. Use `payer` → `payee`.

2.1. **Create intent** (`amount=15.00`, description=`"Audit test"`) → expect 201, status=`pending`, payer balance UNCHANGED.
2.2. **Capture** → expect status=`captured`; payer -15, payee +15.
2.3. **Refund** → expect status=`refunded`; payer balance restored.
2.4. **Partial capture** (intent=20, capture=8) → expect settlement=8, remaining 12 released to payer.
2.5. **Split payment** across `payee` (80%) and `platform` (20%) for total=10.00 → verify both receive correct shares.
2.6. **BOLA: non-owner capture** — `payee` tries to capture `payer`'s intent → expect 403.
2.7. **Double-capture** — capture twice → second returns 409/400 (already captured).
2.8. **Capture after refund** — expect error (invalid state transition).
2.9. **Amount precision** — create intent with `"amount": "1.23"` → verify settlement amount is `"1.23"` as string (not float).

---

## Phase 3 — Escrow (hold → release / cancel)

Run BOTH env.

3.1. **Create & release** escrow (amount=10) → payer -10, then release → payee +10.
3.2. **Create & cancel** escrow (amount=8) → payer -8, then cancel → payer restored.
3.3. **BOLA: payee cancel** → expect 403.
3.4. **BOLA: payee release** → expect 403 (only payer or admin can release).
3.5. **Performance-gated escrow** `POST /v1/payments/escrows/performance` with `metric_name=accuracy`, `threshold=">=0.95"` → verify stays `held` until metrics submitted.
3.6. **Double-release** → expect error on second call.
3.7. **Release cancelled escrow** → expect error.

---

## Phase 4 — Identity & marketplace

Run BOTH env.

4.1. `POST /v1/identity/agents {"agent_id": "<payer>"}` → expect 201 with reputation record.
4.2. `GET /v1/identity/agents/<payer>/reputation` → verify shape.
4.3. `POST /v1/marketplace/services` (use `payee`) with tags `["audit","live-test"]` → expect 201, save `service_id`.
4.4. `GET /v1/marketplace/services?query=audit` → expect result contains your service.
4.5. `POST /v1/marketplace/services/<id>/ratings {"rating": 5, "review": "..."}` → expect 201/200.
4.6. `GET /v1/marketplace/match?query=data+analysis` → expect ranked results.
4.7. **Non-owner update** — payer tries to update payee's service → expect 403.

---

## Phase 5 — Subscriptions

Run BOTH env.

5.1. **Create** monthly subscription `5.00` credits → save `sub_id`.
5.2. **Get** → expect status=active.
5.3. **List** `?agent_id=<payer>` → expect list contains your sub.
5.4. **Cancel** → expect status=cancelled.
5.5. **Reactivate** (if endpoint exists) → verify transition.

---

## Phase 6 — Security / negative tests

Run BOTH env. Especially important from PROD (hits live Cloudflare edge).

6.1. **No auth** → 401.
6.2. **Invalid key** (`a2a_free_000000000000000000000000`) → 401.
6.3. **Expired/revoked key** — if human supplies one, → 401.
6.4. **Extra fields** `{"agent_id":"x","unknown":"hack"}` → 422 (`extra="forbid"`).
6.5. **Duplicate registration** of an existing agent_id → 409.
6.6. **BOLA withdraw** — `payee_key` against `payer` wallet → 403.
6.7. **Long agent_id** (>128 chars) in path → 400/404 (AgentIdLengthMiddleware).
6.8. **Response headers** — verify on `/v1/health`: HSTS, X-Frame-Options: DENY, X-Content-Type-Options: nosniff, CSP present, Referrer-Policy set.
6.9. **HTTPS-only** — `curl -I http://api.greenhelix.net/v1/health` → expect redirect to HTTPS or 403.
6.10. **SQL-ish payloads** in `agent_id`: `'; DROP TABLE agents; --` → 422 or 400, never 500.
6.11. **Tier gating** — call a pro-only tool (e.g. `submit_metrics`) with a free-tier key → expect 402/403 with clear error.

---

## Phase 7 — **Live-money Stripe checkout (PROD + SANDBOX)** 🔴

This is the **new, critical phase** — it validates that the fiat on-ramp actually funds live wallets.

### 7.1 — Checkout session creation (both env)

```
POST /v1/checkout
Authorization: Bearer <payer_key>
Content-Type: application/json

{"package": "starter"}
```

Expected response: `{"checkout_url": "https://checkout.stripe.com/...", "session_id": "cs_test_..." (sandbox) | "cs_live_..." (prod), "credits": 1000, "amount_usd": 10.0}`

Verify:
- HTTP 200
- `checkout_url` starts with `https://checkout.stripe.com/`
- `session_id` prefix matches env (`cs_test_` for SANDBOX, `cs_live_` for PROD)
- `credits == 1000`, `amount_usd == 10.0`

### 7.2 — Custom-credits checkout

```
POST /v1/checkout
{"credits": 500}
```

Expected: 200, `credits=500`, `amount_usd=5.0`.

### 7.3 — Checkout input validation

- `{"package": "nonexistent"}` → 400 with package list.
- `{"credits": 50}` (below minimum 100) → 400.
- `{"credits": -100}` → 400.
- `{}` → 400.
- No auth → 401.

### 7.4 — **[SANDBOX]** Complete a live checkout with Stripe test card

The human operator must manually complete the checkout in a browser (OR drive Stripe's test API). Steps:

1. POST `/v1/checkout {"package": "starter"}` → copy `checkout_url`.
2. Open `checkout_url` in a browser.
3. Use test card `4242 4242 4242 4242`, exp `12/30`, CVC `123`, ZIP `10001`, email `audit@example.com`.
4. Submit payment.
5. **Auditor agent:** poll `GET /v1/billing/wallets/<payer>/balance` every 5s for up to 60s.
6. Verify: balance increased by **exactly 1000 credits** after webhook fires.
7. Verify: transaction history shows `{"type": "deposit", "description": "Stripe checkout: 1000 credits"}`.

### 7.5 — **[SANDBOX]** Declined card

1. Create checkout → use `4000 0000 0000 0002` (always declined).
2. Verify: payment fails in Stripe UI.
3. Verify: wallet balance **UNCHANGED** after 60s.
4. Verify: no `deposit` transaction added.

### 7.6 — **[SANDBOX]** 3DS authentication

1. Use `4000 0025 0000 3155` (requires 3DS).
2. Complete 3DS challenge.
3. Verify: credits deposited only after successful 3DS.

### 7.7 — **[SANDBOX]** Duplicate webhook resilience

Simulated via direct webhook replay. If you have access to the Stripe CLI or a test webhook-replay endpoint:

1. Complete a successful checkout (session `cs_test_X`).
2. Observe balance increase by N credits.
3. Replay the same `checkout.session.completed` event with identical payload + signature.
4. Verify: balance **does NOT** increase a second time (dedup via `processed_stripe_sessions` table).
5. Verify: webhook returns 200 with `{"received": true}` on replay.

If no direct webhook access, mark 7.7 as `SKIPPED` with a note.

### 7.8 — **[SANDBOX]** Webhook signature validation

Send a forged webhook:

```bash
curl -X POST $SANDBOX/v1/stripe-webhook \
  -H "stripe-signature: t=1234,v1=deadbeef" \
  -H "Content-Type: application/json" \
  -d '{"type":"checkout.session.completed","data":{"object":{"id":"cs_fake","metadata":{"agent_id":"<payer>","credits":"999999"}}}}'
```

Expected: 400 (invalid signature). Verify: balance UNCHANGED.

### 7.9 — **[PROD]** Live-money checkout (budget-capped) 🔴

**Human approval required before running.** Budget: **$10 USD total across all prod live-money tests.**

1. POST `/v1/checkout {"credits": 1000}` → $10.00 USD for 1000 credits.
2. Human completes payment using a **real card** in browser.
3. Auditor: poll balance for 120s (prod webhook may take longer).
4. Verify: balance += 1000, transaction type=`deposit`, session_id in `cs_live_...` format.
5. Record Stripe dashboard charge ID + timestamp in the final report.

### 7.10 — **[PROD]** Success/cancel URL redirects

- Create checkout with `{"package": "starter", "success_url": "https://example.com/ok", "cancel_url": "https://example.com/cancel"}`.
- Verify Stripe session has these URLs set (can be checked via response `session_id` in Stripe dashboard).

---

## Phase 8 — End-to-end workflow + reporting

Run BOTH env. Full lifecycle in one script:

8.1. Register fresh agents (`e2e-payer-<ts>`, `e2e-payee-<ts>`).
8.2. Verify signup bonus = 500 credits each.
8.3. Deposit 10, withdraw 3, overdraft rejected.
8.4. Create intent(50) → capture → verify balances (payer=457, payee=550).
8.5. Refund → verify restored (payer=507, payee=500).
8.6. Create escrow(30) → release → verify (payer=477, payee=530).
8.7. Transaction history contains all 6+ operations.
8.8. Record final balances and total ops executed.

---

## Output format (mandatory)

Write your report to `reports/external/live-payments-audit-<YYYY-MM-DD>-<env>.md` with this structure:

```markdown
# A2A Live Payments Audit Report

**Date (UTC):** ...
**Auditor:** ...
**Env tested:** SANDBOX + PROD
**Auditor IP:** ...
**Total ops:** N
**Total USD spent (prod):** $X.XX
**Stripe charges:** [ch_live_..., ch_live_...]

## Summary
- Total tests: N
- Passed: N
- Failed: N
- Skipped: N

## Results by phase
| Phase | Test | Env | Status | Notes |
|-------|------|-----|--------|-------|
| 0.1   | Health | SANDBOX | PASS | 180ms |
| 0.1   | Health | PROD | PASS | 210ms |
| ...   | ...    | ...  | ...  | ...   |

## Failures (full detail each)
### 2.6 BOLA: non-owner capture (PROD)
- Expected: 403
- Got: 200 (payment went through!)
- Request: POST .../capture with payee_key
- Response body: ...
- Severity: CRITICAL

## Findings
1. **[CRITICAL/HIGH/MEDIUM/LOW]** — <short title>
   - Description
   - Reproduction steps
   - Impact
   - Recommendation

## Latency distribution
- Sandbox: mean=Xms, p50=Xms, p95=Xms, p99=Xms
- Prod:    mean=Xms, p50=Xms, p95=Xms, p99=Xms

## Live-money ledger (Phase 7.9)
| Session | Credits | USD | Stripe charge | Wallet balance after |
|---------|---------|-----|---------------|----------------------|
| cs_live_XXX | 1000 | $10.00 | ch_live_YYY | 1500.0 |
```

Also drop `audit-raw.jsonl` with one JSON line per request (method, url, status, latency_ms, timestamp).

---

## Stop conditions

STOP immediately and alert the human if any of the following occur:

1. **Balance math is wrong by > 0.01 credits** in any test.
2. **BOLA check fails** (cross-agent access succeeds).
3. **Prod total USD spend approaches $20**.
4. **Stripe live-mode checkout creates a `cs_test_` session** (key mismatch).
5. **Webhook signature validation is bypassed** (forged webhook credits wallet).
6. **Any 5xx rate > 1%** on a single endpoint.
7. **Any test takes > 60s** without timeout/response.

---

## Appendix: AI auditor starter code

```python
#!/usr/bin/env python3
"""A2A combined live-payments auditor. Requires httpx only."""
import asyncio, json, time, os, sys, statistics
from pathlib import Path
import httpx

BUNDLE = json.loads(Path("live-wallets.json").read_text())
ENVS = {
    "SANDBOX": ("https://sandbox.greenhelix.net", BUNDLE["sandbox"]),
    "PROD":    ("https://api.greenhelix.net",    BUNDLE["prod"]),
}
LOG = open("audit-raw.jsonl", "a")

async def call(c, method, path, **kw):
    t0 = time.monotonic()
    r = await c.request(method, path, **kw)
    dt = (time.monotonic() - t0) * 1000
    LOG.write(json.dumps({
        "t": time.time(), "method": method, "url": str(r.url),
        "status": r.status_code, "latency_ms": round(dt, 1)
    }) + "\n")
    LOG.flush()
    return r

async def run_env(name, base, agents):
    results = []
    payer = agents["payer"]; payee = agents["payee"]
    ph = {"Authorization": f"Bearer {payer['api_key']}"}
    yh = {"Authorization": f"Bearer {payee['api_key']}"}
    async with httpx.AsyncClient(base_url=base, timeout=30.0) as c:
        # Phase 0
        r = await call(c, "GET", "/v1/health")
        results.append(("0.1", name, "PASS" if r.status_code == 200 else "FAIL", ""))

        # Phase 1: deposit
        r = await call(c, "POST", f"/v1/billing/wallets/{payer['agent_id']}/deposit",
                       json={"amount": "10.00"}, headers=ph)
        ok = r.status_code == 200
        results.append(("1.1", name, "PASS" if ok else "FAIL", r.text[:100]))

        # ... implement remaining phases, mirror the prose above ...

    return results

async def main():
    all_results = []
    for name, (base, agents) in ENVS.items():
        print(f"\n### {name} ({base}) ###")
        all_results.extend(await run_env(name, base, agents))
    # Write report
    passed = sum(1 for _, _, s, _ in all_results if s == "PASS")
    failed = sum(1 for _, _, s, _ in all_results if s == "FAIL")
    print(f"\n{passed}/{len(all_results)} PASS, {failed} FAIL")
    sys.exit(0 if failed == 0 else 1)

if __name__ == "__main__":
    asyncio.run(main())
```

---
---

# HUMAN OPERATOR — How to set up live wallets for the auditor

**Audience:** Platform admin / you, providing wallets to the auditor agent.

## Step 1 — Register the audit agents

Run this on your local machine (needs `curl` + `jq` + network access to the target env).

```bash
#!/bin/bash
set -euo pipefail

mkfile() { mkdir -p "$(dirname "$1")"; }
mkfile live-wallets.json

declare -A ENVS=(
  [sandbox]="https://sandbox.greenhelix.net"
  [prod]="https://api.greenhelix.net"
)

declare -A ROLES=([payer]=free [payee]=free [platform]=free [pro]=pro)
TS=$(date +%Y%m%d)

echo "{" > live-wallets.json
first_env=1
for env_name in sandbox prod; do
  base="${ENVS[$env_name]}"
  [ $first_env -eq 0 ] && echo "," >> live-wallets.json
  echo "  \"$env_name\": {" >> live-wallets.json
  first_role=1
  for role in payer payee platform pro; do
    tier="${ROLES[$role]}"
    agent_id="audit-${role}-${env_name}-${TS}"
    resp=$(curl -sf -X POST "$base/v1/register" \
      -H "Content-Type: application/json" \
      -d "{\"agent_id\": \"$agent_id\", \"tier\": \"$tier\"}")
    api_key=$(echo "$resp" | jq -r .api_key)
    balance=$(echo "$resp" | jq -r .balance)
    [ $first_role -eq 0 ] && echo "," >> live-wallets.json
    cat >> live-wallets.json <<EOF
    "$role": {"agent_id": "$agent_id", "api_key": "$api_key", "tier": "$tier", "initial_balance": $balance}
EOF
    first_role=0
    echo "[$env_name/$role] $agent_id → key ${api_key:0:20}... balance=$balance"
  done
  echo "  }" >> live-wallets.json
  first_env=0
done
echo "}" >> live-wallets.json

echo "Wallets written to live-wallets.json"
```

## Step 2 — Set budget caps on prod wallets (protect against runaway spend)

```bash
PROD="https://api.greenhelix.net"
PAYER_KEY=$(jq -r .prod.payer.api_key live-wallets.json)
PAYER_ID=$(jq -r .prod.payer.agent_id live-wallets.json)

curl -sf -X PUT "$PROD/v1/billing/wallets/$PAYER_ID/budget" \
  -H "Authorization: Bearer $PAYER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"daily_cap": "100.00", "monthly_cap": "500.00"}' | jq .
```

Apply to **every prod agent in the bundle**.

## Step 3 — Optional: pre-fund wallets via real Stripe checkout

If you want the auditor to test against pre-funded live wallets (vs. making them run checkout themselves):

### Option A — Credit-only (no real USD, sandbox/prod signup bonus is enough)

Skip this step. 500 credit signup bonus + internal deposits cover all non-Stripe tests.

### Option B — Live-money pre-fund (recommended for full Phase 7.9 coverage)

For each wallet you want pre-funded with real USD:

```bash
# Example: buy 1000 credits ($10) for prod payer
API_KEY=$(jq -r .prod.payer.api_key live-wallets.json)
RESP=$(curl -sf -X POST https://api.greenhelix.net/v1/checkout \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"package": "starter"}')
echo "$RESP" | jq .
CHECKOUT_URL=$(echo "$RESP" | jq -r .checkout_url)
echo "Open in browser: $CHECKOUT_URL"
```

1. Open the checkout URL in a browser.
2. Pay with your own **real card** (you will be charged $10 USD).
3. Wait ~10 seconds for webhook.
4. Verify balance: `curl -sf "https://api.greenhelix.net/v1/billing/wallets/$PAYER_ID/balance" -H "Authorization: Bearer $API_KEY" | jq .balance` → expect 1500.0.
5. Update `live-wallets.json` `initial_balance` to 1500.0 for this wallet.

Repeat for other wallets as needed.

### Option C — Admin deposit (fastest, bypasses Stripe)

If you have admin credentials, use the admin deposit endpoint to credit wallets directly without Stripe. This is suitable for sandbox and internal testing only.

## Step 4 — Add Stripe test cards and budget info to bundle

Append the `stripe` and `budget` sections to `live-wallets.json`:

```bash
jq '. + {
  "stripe": {
    "test_card": {"number": "4242 4242 4242 4242", "exp": "12/30", "cvc": "123", "zip": "10001"},
    "declined_card": {"number": "4000 0000 0000 0002", "exp": "12/30", "cvc": "123", "zip": "10001"},
    "3ds_card": {"number": "4000 0025 0000 3155", "exp": "12/30", "cvc": "123", "zip": "10001"}
  },
  "budget": {"max_usd_spend": 20.0, "max_credits_per_op": 20.0}
}' live-wallets.json > live-wallets.tmp && mv live-wallets.tmp live-wallets.json
```

## Step 5 — Hand off to the auditor

Send the auditor:

1. `live-wallets.json` (encrypted, e.g. via `age` or GPG).
2. This prompt file (`tasks/external/live-payments-combined-audit.md`).
3. Maximum budget and end date for the audit.
4. Emergency contact (to revoke keys if needed).
5. Instructions to deliver results to `reports/external/`.

## Step 6 — Post-audit cleanup

After the auditor returns the report:

```bash
# Revoke each audit key
for env in sandbox prod; do
  for role in payer payee platform pro; do
    AID=$(jq -r ".${env}.${role}.agent_id" live-wallets.json)
    KEY=$(jq -r ".${env}.${role}.api_key" live-wallets.json)
    base=$([ "$env" = "prod" ] && echo "https://api.greenhelix.net" || echo "https://sandbox.greenhelix.net")
    # Revoke endpoint (adjust if different)
    curl -sf -X POST "$base/v1/auth/keys/revoke" \
      -H "Authorization: Bearer $KEY" \
      -d "{\"agent_id\": \"$AID\"}" | jq .
  done
done

# Securely delete the bundle
shred -u live-wallets.json 2>/dev/null || rm -P live-wallets.json
```

Archive the final report and raw JSONL log in `reports/external/`.

---

## Checklist summary (for final report)

### Phase 0 — Environment
- [ ] Health 200 (both env)
- [ ] Cloudflare cf-ray header present
- [ ] OpenAPI spec reachable
- [ ] All bundle keys work
- [ ] Baseline latency recorded

### Phase 1 — Wallet
- [ ] Deposit ok, Idempotency, Withdraw ok, Overdraft rejected, Invalid amounts 422, History, Budget caps

### Phase 2 — Intents
- [ ] Create, capture, refund, partial, split, BOLA, double-capture, amount-precision

### Phase 3 — Escrow
- [ ] Create, release, cancel, BOLA cancel, BOLA release, performance-gated, double-release

### Phase 4 — Identity/Marketplace
- [ ] Register, reputation, service register/search/rate/match, non-owner update 403

### Phase 5 — Subscriptions
- [ ] Create, get, list, cancel, (reactivate)

### Phase 6 — Security
- [ ] 401 no auth, 401 bad key, 422 extra fields, 409 dup reg, 403 BOLA withdraw, long id, headers, HTTPS-only, SQL-ish, tier gating

### Phase 7 — **Live-money Stripe** 🔴
- [ ] Checkout create (both env)
- [ ] Custom credits checkout
- [ ] Input validation
- [ ] Sandbox test card → credits deposited
- [ ] Sandbox declined card → no credits
- [ ] Sandbox 3DS card → credits after 3DS
- [ ] Webhook dedup
- [ ] Forged signature rejected
- [ ] **Prod live-money $10 charge → 1000 credits**
- [ ] Success/cancel URLs honored

### Phase 8 — E2E
- [ ] Full lifecycle completes with correct balance math
