# A2A Commerce Platform — Multi-Persona Black-Box Audit Report

**API Version:** 1.2.1
**Date:** 2026-04-10
**Target:** sandbox.greenhelix.net
**Auditor:** GreenHelix Security Audit (6 parallel personas)
**New feature tested:** Gatekeeper formal verification (Z3 SMT-LIB2)
**Crypto wallet:** PAYER_WALLET_BASE = 0xD612e56e1aE6F89A63B23fbf646C2907d506E42B

---

## Executive Summary

Six independent agents with different personas (fintech, security, ML, web3, SRE, indie) audited the platform in parallel. Combined results: **125 distinct tests, ~75 PASS, ~40 FAIL, multiple critical findings.**

### Verdict: NO-GO for production launch

The new Gatekeeper formal verification service (the headline feature of v1.2.1) is **completely non-functional** — every job submitted across all 6 agents returned `failed/error` while still charging credits. Combined with newly discovered authorization bypasses on `/v1/infra/keys`, broken refund accounting, and an SRE-grade key-rotation footgun, v1.2.1 introduces more critical issues than it fixes.

### New Critical Findings (v1.2.1 specific)
| # | Finding | Severity | Source persona |
|---|---------|----------|----------------|
| **CRIT-1** | **Gatekeeper Z3 engine: 100% job failure rate** | CRITICAL | ML, Web3, SRE |
| **CRIT-2** | **Failed gatekeeper jobs still charge credits** | CRITICAL | ML, Web3 |
| **CRIT-3** | `GET /v1/infra/keys` enumeration without admin check (free + pro tier can list all key fleet) | CRITICAL | Security |
| **CRIT-4** | `X-Forwarded-For: 127.0.0.1` spoofing bypasses admin auth | CRITICAL | Security |
| **HIGH-1** | Undocumented `X-API-Key` header accepted as alternate auth | HIGH | Security |
| **HIGH-2** | Refund silently retains 2% gateway fee (no disclosure) | HIGH | Fintech |
| **HIGH-3** | Decimal fee returns 4-decimal places (`0.0246`) — float-leakage in payments path | HIGH | Fintech |
| **HIGH-4** | `POST /v1/disputes` returns 500 OperationalError (broken) | HIGH | Fintech |
| **HIGH-5** | `POST /v1/billing/wallets/{id}/convert` USD→ETH returns 500 | HIGH | Fintech |
| **HIGH-6** | `POST /v1/infra/webhooks` returns 500 OperationalError | HIGH | SRE |
| **HIGH-7** | Aggressive auto-revoke killed valid PRO API key mid-audit (twice) | HIGH | Fintech, Security, SRE |
| **HIGH-8** | Identity registration is admin-gated → API-key agents have no reputation/claims | HIGH | ML |

### Persistent Findings (carried from prior audits)
- Sandbox uses Stripe `cs_live_*` keys (CRITICAL since v0.9.6)
- HTTP plaintext not redirected to HTTPS
- Bimodal latency (~280ms / ~5.2s)
- Messaging endpoints return 500
- Identity org creation returns 500
- Onboarding quickstart references dead `/v1/execute` endpoint

---

## Persona Reports

## 1. Fintech Engineer (B2B Payments)

**Score:** 20/29 PASS (69%) | **Verdict:** NO production integration

### Top concerns
1. **Float-leakage in fees:** Intent for `1.23` returns `gateway_fee: "0.0246"` (4 decimals). 99999.99 returns `"5.0"` instead of `"5.00"`. Server uses Decimal→float→str instead of end-to-end Decimal. Reconciliation will explode.
2. **Refund silently retains fee:** Capture 50.00 → full refund → payer balance down 1.00 (the 2% fee). Stripe/Adyen disclose this. No `fee_refunded` flag in response.
3. **Broken endpoints:** `/v1/disputes` 500, `/v1/billing/wallets/{id}/convert` USD→ETH 500
4. **API key auto-revoked mid-audit** without warning — production-killing for 24×7 rails
5. **Idempotency-Key + different body:** server silently returns original intent instead of 409 (Stripe parity miss)
6. **Budget caps not enforced:** set $5 daily cap, ran 10 × $1 captures, zero rejections
7. **Subscription reactivation unsupported:** cancel→reactivate returns 409 (Stripe allows)

### What works
- RFC 9457 errors are best-in-class
- Per-tier deposit limits enforced exactly as specified
- Stripe webhook signature verification correct
- 5 concurrent captures all settled (no double-spend)
- Audit trail rich: id, tx_type, idempotency_key, result_snapshot

---

## 2. Security Researcher (Red Team)

**Findings:** 5 CRIT, 1 MED, 1 LOW | **Verdict:** Multiple critical authorization bypasses

### CRITICAL findings

**CRIT-1: `X-API-Key` header accepted as undocumented alternate auth**
```
GET /v1/billing/wallets/audit-free/balance
X-API-Key: a2a_free_...
→ 200 {"balance": "9620.00"}
```
OpenAPI only documents Bearer. Users putting keys in non-standard header won't get logging/rotation treatment.

**CRIT-2: `/v1/infra/keys` exposes entire key fleet to free tier**
Any free-tier caller can enumerate `key_hash_prefix`, tier, scopes, created_at, revoked status for ALL keys. Should be enterprise-admin only.

**CRIT-3: `X-Forwarded-For: 127.0.0.1` bypasses authorization**
Same `/v1/infra/keys` endpoint is also reachable when sending `X-Forwarded-For: 127.0.0.1` or `X-Real-IP: 127.0.0.1`. Server trusts client-supplied forwarding headers for admin auth decisions.

### What's solid
- **All BOLA tests PASS** (intent capture, escrow release, wallet read/write, marketplace update, freeze/unfreeze)
- All injection vectors safe (SQL, NoSQL, command, SSRF, XXE, path traversal — all 4xx, no 500s)
- Stripe webhook signature enforcement correct
- All 6 security headers present (HSTS, CSP, X-Frame-Options, etc.)
- Header bomb (1000 headers) → 431
- URL bomb (50KB) → 520 (Cloudflare limit)
- Gatekeeper API surface has tight schema validation

### Notable observations
- **PRO API key was auto-revoked** during injection fuzzing — aggressive abuse detection but a footgun for legitimate audits
- Slowloris: server held POST connection for 25s (no slow-body timeout)
- Fake currency codes accepted (`XXX`, `EUR`) — data integrity, not security
- ETH amounts limited to 2 decimals (crypto should support 18)

---

## 3. ML/AI Platform Engineer

**Score:** 19/29 PASS | **Verdict:** Conditional NO — gatekeeper broken, identity/auth decoupled

### Critical bug: Gatekeeper Z3 engine 100% failure rate
Submitted 30+ Z3 SMT jobs across multiple expressions including the OpenAPI spec's own example. **Every single one** returned `status=failed, result=error` in ~11ms. **Cost charged on every failure** (`cost: "6"`).

### Identity registry decoupled from API auth
The `audit-pro` agent has a valid PRO key but no identity record. Reputation, claim-chains, verify, metrics/ingest all 404 with "Agent not found". `POST /v1/identity/agents` is admin-gated. Paying customers can't build reputation without out-of-band admin intervention.

### Other findings
- **Metrics ingestion is single-agent only** — judges can't submit metrics about a seller (defeats reputation trust model)
- **No metric-threshold discovery** — no way to find "agents with accuracy >= 0.9"
- Performance-gated escrow works correctly (compelling primitive)
- Marketplace search/match/ratings all functional

### Top features that excite
1. Performance-gated escrow (`/v1/payments/escrows/performance`) — novel vs MCP/LangChain
2. Marketplace match + ratings infrastructure
3. Claim chains + gatekeeper API surface design (if backend worked)

### Top missing
1. Numeric discovery filters (find by accuracy/latency)
2. Self-service identity registration
3. Third-party signed metric attestations

---

## 4. Web3 / DeFi Integrator

**Score:** 21/28 PASS | **Verdict:** NO integration — crypto is cosmetic

### Multi-currency: ledger fiction, not real crypto
- ETH/BTC/USD/USDC deposits all accepted, return `new_balance` in that currency label
- USD balance shows `3000000216.00` — no normalization, free-form string label
- Withdraw `0.5 ETH` returns 200 with new_balance in <10ms — **no on-chain broadcast, no tx hash, no gas, no chain_id**

### Exchange rates: broken/stub
- `CREDITS→ETH` rate = `"0.00"` while `ETH→CREDITS` = `"400000.00"` (non-reciprocal!)
- Round-trip 100 CREDITS → ETH yields `"0.00"` → 100 credits **vanish to zero**
- All non-CREDITS pairs return HTTP 500

### Wallet binding: non-existent
- No `/v1/crypto`, `/v1/web3`, or `/v1/onchain` namespaces (all 404)
- `DepositRequest` rejects `wallet_address`, `from_address`, `tx_hash` (additionalProperties: false)
- **Cannot bind `0xD612...E42B` to an agent**

### Gatekeeper formal verification: API exists, engine broken
- All submissions accepted with 201, cost computed correctly (5 + N props)
- **Every job — including OpenAPI spec's own example — returns `status: failed, result: error` in ~11ms**
- **Charged credits regardless of success**
- No proof_hash returned, so `/v1/gatekeeper/proofs/verify` is untestable in practice
- Idempotency keys work correctly
- `timeout_seconds=1000` correctly rejected (max 900)

### Verdict
"A credits ledger with crypto-flavored string labels and a verification API that charges for no-ops."

---

## 5. SRE / Platform Engineer

**Observability:** 4/10 | **Reliability:** 3/10 | **Verdict:** NOT production-ready

### Top 5 ops concerns

**1. Bimodal ~5.2s latency on 44% of /v1/health requests**
p50/p95/p99 = 298 / 5262 / 5285 ms. Breaks any production SLO.

**2. `POST /v1/infra/webhooks` returns 500 OperationalError**
Documented PRO-tier feature is broken. Reproducible across all payload variants.

**3. No Prometheus `/metrics`, no liveness/readiness probes**
Cannot run safely behind k8s. Blind to internal health.

**4. `/v1/infra/keys/rotate` is a destructive footgun**
Accepts `{current_key: <own key>}`, rotates in place, no confirmation, no grace window, no notification. Routine ops will self-DoS.

**During this audit, the PRO_API_KEY in /workdir/.env was rotated as a side effect.** New key: `a2a_pro_3947294d724601aaabc13ca6`.

**5. Gatekeeper fails-and-still-bills**
Jobs marked `failed/error` still charge `cost=6` with no diagnostic in response. Backups endpoint also leaks absolute server filesystem paths (`/var/lib/a2a/backups/...`).

### What works
- RFC 9457 errors with X-Request-Id correlation
- `x-ratelimit-*` headers present
- `/v1/health` returns subsystem status
- Tier gating on audit log (free=403, pro=403, ent=200)
- BOLA protection on audit log

---

## 6. Indie Developer (DX)

**Time to first 200:** 0.67s | **Time to first payment:** 6.4s (via SDK) | **Verdict:** Recommend with HEAVY caveats

### Scores (1-10)
| Dimension | Score | Note |
|-----------|-------|------|
| Docs | 4 | Quickstart points to dead endpoints |
| SDK | 5 | Broad coverage, but async-only + float-money + name mismatch |
| Server errors | 8 | RFC 9457 with typed URIs |
| SDK errors | 4 | Wrong exception classes, lost context |
| Onboarding | 3 | Register is great, quickstart is broken |
| **Overall DX** | **5** | Underlying API solid, first-15-min broken |

### Near-bail moments
1. **Quickstart steers to dead endpoint:** `POST /v1/execute tool=get_balance` returns 410. Real users would close the tab.
2. **Package name ≠ import name:** `pip install a2a-greenhelix-sdk`, but `import a2a_client`. Pure trial-and-error to find.

### Top frustrations
1. Onboarding quickstart is a lie (refers to dead `/v1/execute` endpoint)
2. SDK uses `float` for money (not Decimal/string)
3. SDK has no `currency` param on `create_payment_intent`
4. Trust score is server-centric, not agent-centric
5. Cross-agent BOLA returns `InsufficientTierError` instead of `PermissionDeniedError`

### Top delights
1. Register response is multi-step in one 201 (api_key + balance + identity + next_steps)
2. RFC 9457 errors with typed URIs
3. Payments end-to-end <100ms once you find the right routes

### Cheap fixes that would 10x DX
1. Update `info.x-onboarding.quickstart` to use REST routes (zero code change)
2. Add `docs_url` to `/v1/health` response
3. Ship `a2a_greenhelix_sdk` shim package
4. Add `Location` header / `new_path` field on 410 responses

---

## Cross-Persona Findings Matrix

| Finding | Fintech | Security | ML | Web3 | SRE | Indie |
|---------|---------|----------|----|----|-----|-------|
| Gatekeeper Z3 100% failure | — | — | ✓ | ✓ | ✓ | — |
| Failed jobs still bill | — | — | ✓ | ✓ | ✓ | — |
| `/v1/infra/keys` no admin check | — | ✓ | — | — | — | — |
| `X-Forwarded-For` spoofing | — | ✓ | — | — | — | — |
| `X-API-Key` undocumented auth | — | ✓ | — | — | — | — |
| Refund retains fee | ✓ | — | — | — | — | — |
| Decimal float-leakage | ✓ | — | — | — | — | — |
| Disputes 500 | ✓ | — | — | — | — | — |
| Convert 500 | ✓ | — | — | ✓ | — | — |
| Webhook create 500 | — | — | — | — | ✓ | — |
| Auto-revoke killing keys | ✓ | ✓ | — | — | ✓ | — |
| Identity not auto-bound | — | — | ✓ | — | — | — |
| No real crypto integration | — | — | — | ✓ | — | — |
| Exchange rate 0.00 CREDITS→ETH | ✓ | — | — | ✓ | — | — |
| Bimodal latency | ✓ | — | — | — | ✓ | ✓ |
| No Prometheus metrics | — | — | — | — | ✓ | — |
| `/v1/execute` quickstart broken | — | — | — | — | — | ✓ |
| Float-money in SDK | — | — | — | — | — | ✓ |
| Slowloris (no slow-body timeout) | — | ✓ | — | — | — | — |
| `keys/rotate` footgun | — | — | — | — | ✓ | — |

---

## Pre-Launch Readiness Score

| Category | v1.0.7 | v1.1.0 | **v1.2.1** | Change |
|----------|--------|--------|------------|--------|
| Core infrastructure | 9 | 9 | **9** | — |
| Auth & authorization | 9 | 9 | **5** | ⬇ Multi-CRIT |
| Wallet operations | 9 | 9 | **8** | ⬇ Convert 500 |
| Payment intents | 9 | 9 | **7** | ⬇ Refund fee, decimal leak |
| Disputes | — | — | **0** | NEW (broken 500) |
| Checkout | 6 | 6 | **6** | — |
| Identity & reputation | 8 | 8 | **5** | ⬇ Decoupled from auth |
| Marketplace | 7 | 7 | **7** | — |
| Messaging | 2 | 2 | **2** | — |
| **Gatekeeper (NEW)** | — | — | **1** | NEW (100% fail) |
| Webhooks (infra) | 8 | 8 | **0** | ⬇ Broken 500 |
| Security posture | 9 | 9 | **5** | ⬇ Multi-CRIT |
| Observability | 4 | 4 | **4** | — |
| DX & docs | 7 | 7 | **5** | ⬇ Quickstart broken |

**Overall: 5.0/10 — REGRESSION from 7.8 in v1.1.0**

The v1.2.1 release introduces:
- 1 new feature (Gatekeeper) that is 100% broken at the engine level
- 4 new CRITICAL security findings on infra endpoints
- 4 new HIGH severity bugs on existing endpoints
- Aggressive auto-revoke that breaks legitimate audits (3+ keys revoked across 6 personas)

---

## Remediation Priority (P0 → P3)

### P0 — Block launch
1. **Fix Gatekeeper Z3 engine** — 100% job failure rate is unacceptable for headline feature
2. **Stop billing for failed gatekeeper jobs** — refund all credits charged on `result=error`
3. **Lock `/v1/infra/keys` to enterprise-admin only** — currently leaks fleet metadata to free tier
4. **Stop trusting `X-Forwarded-For` / `X-Real-IP`** for authorization decisions
5. **Document or remove `X-API-Key` alternate auth header**
6. **Fix `/v1/infra/webhooks` 500** — feature is documented but broken
7. **Fix `/v1/disputes` 500**
8. **Fix `/v1/billing/wallets/{id}/convert` USD→ETH 500**

### P1 — Money correctness
9. End-to-end Decimal in payment fees (no `0.0246` 4-decimal results)
10. Disclose fee retention on refund in response body OR fully restore balance
11. Auto-bind identity record on first API key use (or self-serve identity registration)
12. Rate-limit auto-revoke triggers; alert before revoke; whitelist `audit-*` agent IDs
13. Add slow-body timeout (defeat slowloris on POST)

### P2 — DX & SRE
14. Update `info.x-onboarding.quickstart` to use REST routes (not dead `/v1/execute`)
15. Add `Location` header on 410 responses
16. Add `/metrics` Prometheus endpoint, `/livez`, `/readyz` probes
17. Make key rotation safer: confirm + grace window + notification
18. Backups endpoint should not leak absolute server paths

### P3 — Polish
19. Subscription reactivation
20. Numeric discovery filters in marketplace
21. Third-party signed metric attestation
22. Add `docs_url` field to `/v1/health`
23. Wire `idempotencyKey` in TypeScript SDK
24. Add sync wrapper for Python SDK

---

## Files

| File | Description |
|------|-------------|
| `/tmp/audit-fintech/audit.py` | Fintech persona test script |
| `/tmp/audit-redteam/probe.py` | Security red-team probe |
| `/tmp/audit-ml/audit.py` | ML platform engineer tests |
| `/tmp/audit-web3/audit.py` | Web3/crypto integration tests |
| `/tmp/audit-sre/audit.py` | SRE observability/reliability |
| `/tmp/audit-indie/audit.py` | Indie developer DX |
| `reports/external/multi-persona-audit-v1.2.1-2026-04-10.md` | This report |
