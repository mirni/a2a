# Security & Feature Audit Report: Green Helix A2A API (v0.8.4)

**Target:** `https://api.greenhelix.net/v1`
**Date:** 2026-04-02
**Auditor:** Automated Security Audit (Claude + GreenHelix-SecurityAudit/1.0)
**Server Version:** 0.8.4 (REST API, refactored from v0.5.3 `/v1/execute` to 100 dedicated REST endpoints)
**Test Data:** 117 tests / 331 HTTP requests / 12 findings
**Prior Audit:** v0.5.3 (2026-04-01) — 24 findings, server crashed on all authenticated requests (AUTH-500)

---

## Executive Summary

Server v0.8.4 represents a major improvement over v0.5.3. The AUTH-500 crash is fixed, Pydantic strict validation (`additionalProperties: false`) is enforced, and BOLA is properly implemented across all tested endpoints. However, **6 CRITICAL, 2 HIGH, and 4 MEDIUM** findings remain:

| Severity | Count | Categories |
|----------|-------|-----------|
| CRITICAL | 6 | Authentication (1), BFLA (3), Race Condition (1), BOLA (1) |
| HIGH | 2 | Rate Limiting (2) |
| MEDIUM | 4 | Business Logic (3), Intent Capture Crash (1) |

---

## 1. Edge Security & Infrastructure

### [PASS] TLS & Certificate
- **Protocol:** TLSv1.3 on all hosts
- **Cipher:** TLS_AES_256_GCM_SHA384 (256-bit)
- **Certificate:** Let's Encrypt wildcard `*.greenhelix.net`
- **HSTS:** `max-age=31536000; includeSubDomains` present

### [PASS] Security Headers
All 4 required security headers present on success AND error responses:
- `strict-transport-security`
- `x-content-type-options: nosniff`
- `x-frame-options: DENY`
- `content-security-policy: default-src 'none'`

### [PASS] Rate Limit Headers Present
Headers `x-ratelimit-limit`, `x-ratelimit-remaining`, `x-ratelimit-reset` present.
**However:** Not enforced — see Section 7.

**Note:** Rate limit value changed mid-test from `x-ratelimit-limit: 1000` to `10000`. Investigate whether this is dynamic scaling or a configuration drift.

---

## 2. Agent Authentication & Identity

### [PASS] Key Validation
All 3 tiered API keys authenticate correctly:
- `audit-free` (free tier): balance=10,000.00
- `audit-pro` (pro tier): balance=100,000.00 (initially; drifted to 99,999.98 due to test deposits/withdrawals)
- `audit-admin` (enterprise tier): balance=999,999.00

### [PASS] Invalid Key Rejection
6 invalid key formats all properly rejected (401/403):
- Empty bearer, null, wrong prefix, short key, SQL injection in key, random garbage

### [PASS] IP Spoofing Prevention
`X-Forwarded-For`, `X-Real-IP`, `X-Original-URL` header spoofing does not bypass authentication.

### [CRITICAL] AUTH-OLD-KEY — Old API Key Still Accepted
**Finding ID:** AUTH-OLD-KEY
**OWASP:** A07:2021 — Identification and Authentication Failures
**CVSS:** 9.0

The old API key from the previous deployment (`a2a_pro_307702814d8bdf0471ba5621`) returns HTTP 200 when used to query balance. This key should have been revoked when the server was upgraded.

**Impact:** Any previously-issued key remains valid indefinitely. If a key is compromised, there is no way to invalidate it.
**Evidence:** `GET /v1/billing/wallets/audit-pro/balance` with old key → 200
**Remediation:** Implement key rotation and revocation. Invalidate all keys from previous deployment. Add key expiration timestamps.

---

## 3. Authorization & Access Control

### [PASS] Broken Object Level Authorization (BOLA) — Read Operations
**16 tests, 0 findings.** All cross-agent read operations properly return 403:
- free→pro: balance, transactions, usage, budget, revenue, analytics, messages, payment_history — all 403
- pro→admin: same 8 endpoints — all 403

Response format: RFC 9457 Problem Detail (`{"type": "...", "title": "Forbidden", "status": 403, "detail": "..."}`)

### [PASS] BOLA — Write Operations (Deposit/Withdraw)
- pro→admin deposit: 403
- pro→admin withdraw: 403
- pro→free freeze: 403

### [CRITICAL] ESCROW-CANCEL-BOLA — Non-Payer Can Cancel Escrow
**Finding ID:** ESCROW-CANCEL-BOLA
**OWASP:** API1:2023 — Broken Object Level Authorization
**CVSS:** 9.0

A free-tier agent successfully cancelled an escrow created by the pro agent:
1. Pro creates escrow (payer=pro, payee=free, amount=1.0) → 201, id=`6532e9ef...`
2. Free attempts release → 403 (correctly blocked)
3. **Free cancels escrow → 200 (should be 403)**
4. Escrow status after: "refunded"

**Impact:** Any authenticated agent can cancel any escrow, triggering fund refunds to the payer. This enables griefing attacks and disruption of payment flows.
**Remediation:** Enforce payer-only access on escrow cancel. Only the payer (or admin) should be able to cancel an escrow.

### [CRITICAL] BFLA — 3 Admin Endpoints Accessible to Non-Admin Keys
**OWASP:** API5:2023 — Broken Function Level Authorization

| Finding ID | Endpoint | Accessible By | Status |
|-----------|----------|---------------|--------|
| BFLA-PROCESS_SUBS-PRO | `POST /v1/payments/subscriptions/process-due` | pro key | 200 |
| BFLA-REVOKE_KEY-FREE | `POST /v1/infra/keys/revoke` | free key | 200 |
| BFLA-REVOKE_KEY-PRO | `POST /v1/infra/keys/revoke` | pro key | 200 |

**Properly blocked admin endpoints (403 for free/pro):**
- `GET /v1/infra/audit-log`
- `GET /v1/infra/databases/backups`
- `POST /v1/infra/databases/billing/backup`
- `POST /v1/infra/databases/billing/restore`
- `GET /v1/infra/databases/billing/integrity`
- `POST /v1/infra/keys` (returns 403 for all tiers including enterprise)

**Impact:** Any authenticated agent (even free tier) can revoke API keys. Pro agents can trigger subscription processing. This enables denial-of-service against other agents.
**Remediation:** Add admin-tier authorization check to `POST /v1/payments/subscriptions/process-due` and `POST /v1/infra/keys/revoke`.

### [PASS] Tier Enforcement
Free key cannot access pro-tier endpoints:
- `POST /v1/identity/metrics/ingest` → 403
- `GET /v1/identity/agents/{agent_id}/claim-chains` → 403

---

## 4. Business Logic & Financial Integrity

### [CRITICAL] RACE-DEP — Race Condition on Concurrent Deposits
**Finding ID:** RACE-DEP
**OWASP:** A04:2021 — Insecure Design
**CVSS:** 9.0

10 concurrent deposit requests (1.0 each) all returned HTTP 200 (success), but the balance did not increase:
- **Before:** 99,999.98
- **Expected after 10 deposits:** 100,009.98
- **Actual after:** 99,999.98

This indicates a **lost update** race condition — likely no row-level locking or `SELECT ... FOR UPDATE` on the balance table.

Similarly, 10 concurrent withdrawals all returned 200 but balance remained unchanged.

**Impact:** Financial operations under concurrent load are silently lost. Agents believe their deposits/withdrawals succeeded when they did not. This can lead to accounting discrepancies and fund loss.
**Remediation:** Use database-level serialization for balance operations (`SELECT ... FOR UPDATE`, or `UPDATE wallets SET balance = balance + $1 WHERE agent_id = $2 RETURNING balance`). Consider implementing optimistic concurrency control with version counters.

### [PASS] Idempotency
Two identical deposits with the same description were both processed (s1=200, s2=200), balance increased by 10 (both counted). No built-in idempotency deduplication exists — this is expected behavior if no `Idempotency-Key` header is implemented, but a **risk** for clients that retry on timeout.

### [MEDIUM] AMT-500 — Negative/Zero Amounts Cause Server Crash
**Finding IDs:** AMT-500-NEGATIVE, AMT-500-NEGATIVE_SMALL, AMT-500-ZERO
**OWASP:** API7:2023 — Server Side Request Forgery (misclassified — actually input validation)

| Amount | Status | Expected |
|--------|--------|----------|
| -100 | 500 | 422 |
| -0.01 | 500 | 422 |
| 0 | 500 | 422 |
| 999999999 | 200 | 200 (or 422 based on policy) |

Server crashes on negative and zero deposit amounts instead of returning a validation error.

**Impact:** Easy to trigger server errors. Combined with no rate limiting, an attacker could cause sustained 500s by sending negative deposits.
**Remediation:** Add `amount > 0` validation in DepositRequest/WithdrawRequest validators (Pydantic `gt=0`).

### [PASS] Escrow Lifecycle
Escrow creation works correctly with the REST API schema (`payer`/`payee` fields):
- Create: 201 with escrow ID
- Release by wrong agent: 403 (correct)
- Cancel by wrong agent: 200 (**BOLA finding above**)

### [MEDIUM] INTENT-CAPTURE-500 — Intent Capture Crashes
**Finding ID:** INTENT-CAPTURE-500

Intent creation works (201), but both capture operations crash:
- Capture by wrong agent → 500 (should be 403)
- Capture by owner → 500 (should be 200)
- Partial capture → 500

The entire intent capture flow is broken.

**Remediation:** Fix the intent capture handler. Add ownership check before processing.

---

## 5. Data Validation & Injection

### [PASS] SQL Injection
3 SQLi payloads in path parameters and 3 in query parameters — all properly handled:
- Path: returned 403 (BOLA check on invalid agent ID)
- Query: returned 200 with empty/default results (no injection)

### [PASS] SSRF via Webhooks
5 SSRF payloads tested against `POST /v1/infra/webhooks` (with correct schema including `secret` field):
- `http://localhost:8080/hook` → 400
- `http://169.254.169.254/latest/meta-data/` → 400
- `http://metadata.google.internal/computeMetadata/v1/` → 400
- `http://10.0.0.1:5432/` → 400
- `file:///etc/passwd` → 400

All SSRF vectors blocked.

### [PASS] Path Traversal
3 path traversal payloads (including URL-encoded variants) — all returned 404 or 403. No file content disclosed.

### [PASS] Type Confusion (Improved from v0.5.3)
5 type confusion tests on deposit endpoint:
- `"not-a-number"` → 422 (correct Pydantic validation)
- `null` → 422
- `[1, 2]` → 422
- `{"val": 1}` → 422
- `true` → 422

**Improvement:** v0.5.3 returned 500 on 8 type confusion inputs for `create_intent`. v0.8.4 with Pydantic strict validation properly returns 422.

### [PASS] Large Payload
1MB payload (description field with 1M "A" characters) accepted (status=200). Consider adding a max payload size at the application level.

---

## 6. Observability & Auditing

### [PASS] Request ID Uniqueness
5 consecutive requests produced 5 unique `x-request-id` values.

### [PASS] Audit Log Access Control
- Enterprise key → 200 (correct)
- Pro key → 403 (correct)
- Free key → 403 (correct)

### [PASS] Error Information Disclosure
Error responses do not leak:
- Stack traces
- Database errors
- Internal IPs or file paths
- Secret/password information

### [PASS] Signing Key
`GET /v1/signing-key` → 200 (public key endpoint, appropriate for verification)

---

## 7. Rate Limiting

### [HIGH] RL-BURST-30 — No Rate Limiting on Burst Requests
**Finding ID:** RL-BURST-30
**OWASP:** API4:2023 — Unrestricted Resource Consumption

30 concurrent requests to `/v1/billing/wallets/{agent}/balance`: **all returned 200**. No 429 responses.

### [HIGH] RL-SUSTAINED — No Rate Limiting at Sustained Load
**Finding ID:** RL-SUSTAINED

60 sequential requests at 20 req/s: **all returned 200**. No 429 responses.

Rate limit headers are present but decorative:
- `x-ratelimit-limit: 1000` (later `10000`)
- `x-ratelimit-remaining` decrements but never triggers rejection
- No 429 response at any load level tested

**Impact:** Attackers can overwhelm the API with unlimited requests. Combined with the race condition (RACE-DEP), high-frequency concurrent requests could cause widespread data corruption.
**Remediation:** Implement actual rate limiting middleware. Recommended: 100 req/min per API key with burst allowance of 20.

---

## OWASP API Security Top 10 (2023) Coverage

| # | Category | Status | Findings |
|---|----------|--------|----------|
| API1 | Broken Object Level Authorization | **FAIL** | ESCROW-CANCEL-BOLA (escrow cancel) |
| API2 | Broken Authentication | **FAIL** | AUTH-OLD-KEY (old key accepted) |
| API3 | Broken Object Property Level Auth | PASS | Pydantic strict validation enforced |
| API4 | Unrestricted Resource Consumption | **FAIL** | RL-BURST-30, RL-SUSTAINED |
| API5 | Broken Function Level Authorization | **FAIL** | BFLA on 3 admin endpoints |
| API6 | Unrestricted Access to Sensitive Business Flows | **FAIL** | RACE-DEP (race condition) |
| API7 | Server Side Request Forgery | PASS | All SSRF vectors blocked |
| API8 | Security Misconfiguration | PASS | Headers OK, TLS OK |
| API9 | Improper Inventory Management | PASS | 100 REST endpoints well-documented via OpenAPI |
| API10 | Unsafe Consumption of APIs | PASS | Webhook URLs rejected |

**Score: 4/10 categories passing cleanly** (improved from 2/10 in v0.5.3)

---

## Status Distribution (All 331 Requests)

| Status | Count | Meaning |
|--------|-------|---------|
| 200 | 252 | Success |
| 201 | 2 | Created (escrow, intent) |
| 400 | 6 | Bad request (SSRF rejects, schema errors) |
| 401 | 10 | Unauthorized (bad/missing keys) |
| 403 | 41 | Forbidden (BOLA/BFLA blocks, tier enforcement) |
| 404 | 5 | Not found (path traversal, nonexistent paths) |
| 409 | 1 | Conflict |
| 422 | 5 | Validation error (type confusion, bad schema) |
| 500 | 6 | Server error (negative amounts, intent capture) |
| -2 | 3 | Connection errors |

---

## Action Items & Remediation Priority

### P0 — Immediate (Block Release)

1. **[CRITICAL] AUTH-OLD-KEY** — Revoke all keys from previous deployment. Implement key expiration.

2. **[CRITICAL] RACE-DEP** — Add database-level serialization for wallet balance operations. Use `SELECT ... FOR UPDATE` or atomic `UPDATE ... RETURNING`.

3. **[CRITICAL] ESCROW-CANCEL-BOLA** — Add payer ownership check to escrow cancel endpoint.

4. **[CRITICAL] BFLA (3 findings)** — Add admin-tier authorization to:
   - `POST /v1/payments/subscriptions/process-due`
   - `POST /v1/infra/keys/revoke`

### P1 — Short-Term (Next Sprint)

5. **[HIGH] RL-BURST-30 / RL-SUSTAINED** — Implement actual rate limiting. Current headers are decorative.

6. **[MEDIUM] AMT-500-NEGATIVE** — Add `amount > 0` validation to deposit/withdraw request models.

7. **[MEDIUM] INTENT-CAPTURE-500** — Fix intent capture handler (all capture operations crash with 500).

### P2 — Medium-Term

8. **[MEDIUM] No Idempotency** — Consider `Idempotency-Key` header for financial endpoints.

9. **[LOW] Rate limit value drift** — Investigate `x-ratelimit-limit` changing from 1000→10000 mid-session.

10. **[LOW] Key creation auth** — `POST /v1/infra/keys` returns 403 even for enterprise key. Verify this is intentional.

---

## Improvements Since v0.5.3

| Area | v0.5.3 | v0.8.4 |
|------|--------|--------|
| Auth crash (AUTH-500) | ALL authenticated calls → 500 | **FIXED** — all 3 keys work |
| API architecture | Single `/v1/execute` endpoint | 100 dedicated REST endpoints |
| Input validation | Extra fields silently ignored | Pydantic `additionalProperties: false` |
| BOLA | Not testable (500s) | **Fully enforced** (41 × 403) |
| Type confusion | 8 × 500 on `create_intent` | **FIXED** — all return 422 |
| Error format | Inconsistent | RFC 9457 Problem Detail |
| Schema docs | None | OpenAPI 3.1.0 at `/v1/openapi.json` |
| Findings | 24 (2C, 7H, 13M, 2L) | **12** (6C, 2H, 4M) — fewer but some new |

---

*Report generated 2026-04-02 — GreenHelix Security Audit Framework v0.8.4*
