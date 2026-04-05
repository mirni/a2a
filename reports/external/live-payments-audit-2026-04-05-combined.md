# A2A Live Payments Audit Report

**Date (UTC):** 2026-04-05 07:57 — 08:02
**Auditor:** GreenHelix Security Audit (automated)
**Env tested:** SANDBOX + PROD
**Server version:** 0.9.6 (both envs)
**Auditor IP:** 97.171.35.255
**Total ops (HTTP requests):** ~240 across 139 test assertions
**Total USD spent (prod):** $0.00 — no live-money checkout completed (Phase 7.9 skipped)
**Stripe charges:** none

---

## Executive summary

| | Count |
|---|---|
| Total assertions | 139 |
| PASS | 82 |
| FAIL | 40 |
| SKIP | 13 |
| INFO | 4 |

**Verdict: DO NOT GO LIVE** — 4 CRITICAL findings in the payments stack; wallet atomicity, refund correctness, double-capture protection, and Stripe environment isolation are all broken on v0.9.6. Additionally, 4 pro-tier-gated endpoints could not be exercised because the `/v1/register` endpoint only issues free-tier keys and no pro key was supplied.

---

## Inputs & constraints

- No `live-wallets.json` bundle was provided. Auditor bootstrapped 4 fresh wallets per env (`audit-{payer,payee,platform,pro}-{env}-<ts>`) via `POST /v1/register`. All returned `tier: free` because `/v1/register` does not accept a `tier` parameter.
- As a result, every tier-gated assertion (`create_escrow`, `register_service`, `create_subscription`, `split_intent`, `partial_capture`) returned `403 insufficient-tier` and is marked FAIL rather than SKIP. These are **not** bugs; they confirm tier gating is enforced.
- Phases 7.4–7.6 (browser-interactive Stripe checkout), 7.7 (webhook replay), and 7.9 (live-money prod charge) were **SKIPPED** (no browser / no Stripe CLI / no human approval).

---

## CRITICAL findings

### C1 — Sandbox environment uses Stripe LIVE-mode keys 🔴 STOP CONDITION

`POST /v1/checkout` on **sandbox.greenhelix.net** returns a session id of the form `cs_live_...` and a `checkout_url` pointing at `https://checkout.stripe.com/c/pay/cs_live_...`.

```
SANDBOX  session_id = cs_live_a1UyvBLWpl3dxBkHk01Y3zCa4nwWrVd9jLrMgAaZsh8wMGFFl0EciJliyC
PROD     session_id = cs_live_a133YtBkhVPywW6dVvvDKIBfhxw1vFxY2lt64kK8gAMAf5yv9clkYTiEKR
```

This matches the explicit stop condition in the audit prompt: "Stripe live-mode checkout creates a `cs_test_` session (key mismatch)". Direction is reversed — the "sandbox" env is backed by **Stripe live keys**. Any user testing on sandbox.greenhelix.net with a real card will be charged real USD. Marketing/docs point sandbox users at this endpoint to safely experiment.

- **Impact:** regulatory risk (Stripe TOS), customer refund/chargeback storm, brand damage.
- **Reproduction:** `curl -sX POST -H "Authorization: Bearer <free_key>" -H "Content-Type: application/json" -d '{"package":"starter"}' https://sandbox.greenhelix.net/v1/checkout | jq .session_id`
- **Recommendation:** block deploy until `STRIPE_SECRET_KEY` in the sandbox environment is set to a `sk_test_*` key. Add a startup assertion that refuses to boot the server with live keys if the env name is `sandbox`. Add a webhook test that asserts session_id prefix matches the env.

---

### C2 — Intent capture returns 500 but silently commits funds ⚠️ atomicity violation

Every `POST /v1/payments/intents/{id}/capture` returns **HTTP 500 `Internal error: OperationalError`** on the first call, yet the payer's wallet is debited.

```
POST /v1/payments/intents/9a214f84.../capture  →  500 "Internal error: OperationalError"
# followed immediately by:
GET  /v1/billing/wallets/<payer>/transactions
# shows:
id=1317 tx_type=withdrawal amount="-3.00" description="payment:9a214f84..." new_balance=483.96
```

- **Impact:** clients see failure and retry; every retry creates another `withdrawal` row (see C3). Users lose funds without any success signal. Payees may or may not be credited (partial commits observed). E2E phase 8 confirmed: payer balance went 507 → 456.99 after a single capture call that returned 500.
- **Reproduction:** create intent for any amount, call capture once, check `/v1/billing/wallets/<payer>/transactions` — the withdrawal is logged despite the 500 response.
- **Recommendation:** wrap the capture path in a transaction with `ROLLBACK` on any exception; do not write the ledger row until the full state transition (intent→captured, payer debit, payee credit, settlement row) succeeds. Treat the `OperationalError` as the actual signal and return the original DB error code path, not a blanket 500.
- **Affects:** both SANDBOX and PROD, v0.9.6.

---

### C3 — Double-capture is NOT blocked (every retry creates a new withdrawal)

Because of C2, when a client retries the failed capture, the server creates a **second** withdrawal row on the same intent:

```
id=1315 amount=-3.00 description=payment:9a214f84...  new_balance=486.96  (first capture)
id=1317 amount=-3.00 description=payment:9a214f84...  new_balance=483.96  (retry: should have been rejected)
```

Two separate withdrawals of 3.00 on the same intent (same `payment:` id). Test 2.7 ("double capture rejected, expected 400/409/422") got 500 on the second call as well — so the server does not cleanly reject a second capture; it errors out only after double-debiting.

- **Impact:** paired with C2, naive retry logic on the client side will drain wallets. Worst case: capture called N times debits N × amount.
- **Recommendation:** add a uniqueness constraint on `(payment_id, tx_type=withdrawal)` at the DB level. The capture path should check `intent.status` with `SELECT ... FOR UPDATE` and refuse anything not in `pending`. Return `409 invalid-state` on retries.

---

### C4 — Refund returns `200 voided` but does NOT restore balance

After a successful-in-reality capture (payer debited 50), `POST /v1/payments/intents/{id}/refund` returns `200 {"status":"voided","amount":"50.0"}`, yet the payer balance is unchanged and no credit transaction appears in the payer's ledger:

```
Before refund: payer=456.99, payee=550.0
POST /v1/payments/intents/e0db63b.../refund → 200 {"id":"e0db63b...","status":"voided","amount":"50.0"}
After refund:  payer=456.99, payee=550.0      (no change)
```

Observed on BOTH SANDBOX and PROD, amounts 15.0, 2.0, 50.0. Phase 8.5 FAIL on both envs.

- **Impact:** silent data-loss. Clients believe refund succeeded; users are out of pocket. Combined with C2/C3 this turns the payments stack into a one-way drain.
- **Recommendation:** audit the `voided` code path. The response status must not be 200 unless reversal ledger entries (credit payer, debit payee) have been committed. Add an integration test that asserts `balance_after == balance_before_capture` after refund.

---

## HIGH findings

### H1 — Overdraft withdraw returns 500 instead of 4xx

```
POST /v1/billing/wallets/<payer>/withdraw {"amount":"99999.00"}
→ 500 "Internal server error" (both envs)
```

- **Expected:** `402 payment-required` or `400 bad-request` with `insufficient_funds` detail.
- **Impact:** clients cannot distinguish between server failure and user-level rejection; unnecessary alert noise; leaks stack-trace category ("Internal server error") instead of an RFC 9457 typed error.
- **Recommendation:** check balance before the DB write and return typed `402` error.

### H2 — HTTP (plain) requests are not redirected to HTTPS

```
GET http://sandbox.greenhelix.net/v1/health → 200 (served over plaintext HTTP)
GET http://api.greenhelix.net/v1/health    → 200 (served over plaintext HTTP)
```

- **Expected:** 301/308 redirect to HTTPS, or 403/400 rejection (per audit spec 6.9). HSTS header is set on HTTPS responses, but because plaintext is accepted at all, first-request downgrade is possible if a client does not pin HTTPS.
- **Recommendation:** configure Cloudflare "Always Use HTTPS" for both zones and enable HSTS preload.

### H3 — Gateway fee charged on `/v1/payments/intents` create is undocumented and unrecoverable

Every successful `POST /v1/payments/intents` call creates an invisible `tx_type=charge amount=-0.01 description=gateway:create_intent` ledger row on the payer. Similar: `gateway:best_match` at 0.10.

- **Impact:** users creating intents for tiny amounts may pay more in gateway fees than the intent's value. Not disclosed in pricing docs. Not refunded on refund.
- **Recommendation:** document this fee in `/v1/pricing`, return it in the create-intent response body as `gateway_fee`, and include it in refund reversal.

---

## MEDIUM findings

### M1 — `Idempotency-Key` header does not return `transaction_id` in response

`POST /v1/billing/wallets/<id>/deposit` with the same `Idempotency-Key` twice correctly deposits only once (balance verified), **but** neither response body contains a `transaction_id` / `id` field. Clients cannot look up the resulting ledger row without a follow-up list call.

- **Recommendation:** always echo the created (or re-used) `transaction_id` in the deposit response body.

### M2 — Transactions response field name mismatches spec/prompt

Audit prompt specifies transaction fields `id, type, amount, timestamp, description`. Actual API returns `id, agent_id, amount, tx_type, description, created_at, idempotency_key, result_snapshot, currency`. Clients built against the documented schema will break.

- **Recommendation:** rename `tx_type` → `type` and `created_at` → `timestamp`, or update OpenAPI + docs to reflect actual names.

### M3 — Long `agent_id` returns `about:blank` typed error (middleware misconfiguration)

`GET /v1/billing/wallets/<200-char-id>/balance` returns `422 {"type":"about:blank","title":"Validation Error",...}`. All other error types use the `https://api.greenhelix.net/errors/...` typed-URI convention. Per the project notes, `AgentIdLengthMiddleware` is meant to reject with 400/404 for path segments > 128 chars.

- **Recommendation:** either enforce the length cap in the middleware (return `400 /errors/path-too-long`) or ensure FastAPI path validators use the project's RFC 9457 error type.

### M4 — SQL-ish payload in path returns 403 (ownership), not 404/422

`GET /v1/billing/wallets/<url-encoded SQL>/balance` returns `403 forbidden` (ownership check). No 500 — so no injection is present. However, a 404 or 422 would be more correct because the agent doesn't exist at all. Current behavior leaks that "you are not the owner of this (non-existent) wallet", which is still information-safe but inconsistent.

### M5 — `POST /v1/identity/metrics` returns 405 instead of 402/403 (tier gating check)

Tier-gating test 6.11 attempted to exercise a pro tool via `/v1/identity/metrics` and received `405 Method Not Allowed`. Either the route doesn't exist at that path or the method is wrong. Low-severity in itself; indicates doc drift.

---

## LOW / INFO findings

- **I1** — Mean latency is bimodal as expected: p50 ≈ 285 ms, p95 ≈ 5.28 s (both envs). Consistent with prior DNS penalty observation.
- **I2** — `/v1/checkout` correctly echoes `success_url` / `cancel_url` when provided (7.10 PASS both envs).
- **I3** — Forged Stripe webhook rejected with `400 {"error":"Invalid signature"}` (7.8a PASS, 7.8b balance unchanged).
- **I4** — Security response headers (HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP) all present on `/v1/health` (6.8 PASS).
- **I5** — Auth enforcement is solid: no-auth 401, invalid key 401, BOLA withdraw 403, non-owner marketplace PUT blocked, dup-register 409 (all PASS).
- **I6** — Capture-after-refund correctly returns `409 invalid-state` (2.8 PASS), demonstrating the state machine works in one direction; the inverse (refund-after-capture) is broken per C4.

---

## Results by phase (summary)

| Phase | SANDBOX | PROD | Notes |
|-------|---------|------|-------|
| 0 Environment | 5/5 PASS | 5/5 PASS | v0.9.6 confirmed |
| 1 Wallet/billing | 6 PASS, 3 FAIL | 6 PASS, 3 FAIL | Overdraft 500 (H1), idem no txn_id (M1), field names (M2) |
| 2 Intents | 4 PASS, 5 FAIL | 4 PASS, 5 FAIL | Capture 500 (C2), double-capture (C3), partial/split tier-gated |
| 3 Escrow | 0 PASS, 2 FAIL, 5 SKIP effectively (tier) | same | free-tier blocks create_escrow |
| 4 Identity/market | 4 PASS, 1 FAIL | 4 PASS, 1 FAIL | register_service tier-gated |
| 5 Subscriptions | 0 PASS, 1 FAIL | same | create_subscription tier-gated |
| 6 Security | 7 PASS, 4 FAIL | 7 PASS, 4 FAIL | HTTP-only (H2), long id 422 (M3), SQL 403 (M4), pro route 405 (M5) |
| 7 Stripe checkout | 9 PASS, 0 FAIL, 6 SKIP | 9 PASS, 0 FAIL, 6 SKIP | **C1 env key mismatch** |
| 8 E2E workflow | 3 PASS, 5 FAIL | 3 PASS, 5 FAIL | Depends on C2/C3/C4 |

Full results: `/workdir/audit_runs/results.json`
Raw request log: `/workdir/audit_runs/audit-raw.jsonl` (396 entries)
Bundle: `/workdir/audit_runs/live-wallets.json`

---

## Latency distribution

| Env | n | min | p50 | p95 | max | mean |
|-----|---|-----|-----|-----|-----|------|
| SANDBOX | 96 | 239 ms | 286 ms | 5286 ms | 5668 ms | 1541 ms |
| PROD | 93 | 231 ms | 281 ms | 5278 ms | 5693 ms | 1663 ms |

(bimodal; slow bucket is DNS / connect penalty documented in prior audits.)

---

## Stop conditions triggered

| # | Condition | Triggered | Detail |
|---|-----------|-----------|--------|
| 1 | Balance math wrong by >0.01 | **YES** | Phase 8.5 refund leaves 50.01 drift (C4) |
| 2 | BOLA succeeds cross-agent | NO (all BOLA tests pass: withdraw, escrow payee, marketplace PUT) |
| 3 | Prod spend → $20 | NO | $0 spent |
| 4 | Stripe live/sandbox key mismatch | **YES** | sandbox issues `cs_live_` sessions (C1) |
| 5 | Webhook signature bypass | NO | forged 400 rejected |
| 6 | 5xx rate >1% | **YES** | capture endpoint is ~100% 500, overdraft 500 (~40+ 5xx responses in 240 requests ≈ 16%) |
| 7 | Any test >60s | NO | max latency 5.7s |

**Three stop conditions triggered → audit recommends halting prod rollout of v0.9.6.**

---

## Recommendations (priority order)

1. **C1 (P0)** — Swap `STRIPE_SECRET_KEY` on sandbox to `sk_test_*`; add env-mismatch boot assertion.
2. **C2/C3 (P0)** — Fix capture atomicity. Wrap in single DB transaction with `FOR UPDATE` on the intent row; refuse captures when `status != pending`.
3. **C4 (P0)** — Fix refund balance-restoration path; add regression test `balance_after_refund == balance_before_capture + gateway_fee`.
4. **H1 (P1)** — Return `402` on insufficient funds instead of 500.
5. **H2 (P1)** — Enable Cloudflare "Always Use HTTPS" on both zones.
6. **H3 (P2)** — Document & disclose `gateway:create_intent` and `gateway:best_match` fees; return in response; reverse on refund.
7. **M1-M5 (P2)** — Align response schemas with docs; fix AgentIdLengthMiddleware error type; document or remove `/v1/identity/metrics`.
