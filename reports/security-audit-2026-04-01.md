# Security & Feature Audit Report: Green Helix A2A API (v1)

**Date:** 2026-04-01
**Scope:** Full internal security audit of the A2A Commerce Gateway REST API
**Methodology:** Static code analysis of gateway source, routes, tools, middleware, and infrastructure

---

## Executive Summary

The A2A gateway demonstrates **strong security foundations** — cryptographic primitives, input validation, SSRF protection, rate limiting, and admin-tool guards are all well-implemented. However, the Phase 2/3 REST API refactoring introduced a **critical authorization gap**: the v1 REST routers do not call `check_ownership_authorization()`, enabling cross-agent data access (BOLA). Financial logic also has race-condition risks in refunds and in-memory-only deduplication for Stripe webhooks.

**Finding Distribution:**

| Severity | Count |
|----------|-------|
| CRITICAL | 5 |
| HIGH     | 12 |
| MEDIUM   | 10 |
| LOW      | 5 |

---

## Prioritized Action Items & Remediation

### P0 — Fix Before Production (Critical)

#### 1. BOLA: v1 REST Routers Missing Ownership Authorization
**Severity:** CRITICAL
**CWE:** CWE-639 (Authorization Bypass Through User-Controlled Key)

**Root Cause:** `check_ownership_authorization()` is called in `/v1/execute` (line 343–347 of `gateway/src/routes/execute.py`) but **not** in the `require_tool()` dependency used by all v1 REST routers (`gateway/src/deps/tool_context.py`).

**Impact:** Any authenticated agent can:
- Read any other agent's wallet balance, transactions, usage, analytics, revenue, timeseries, budget
- Read any other agent's payment intents, escrows, subscriptions, payment history
- Read any other agent's identity claims, reputation, metrics
- **Write** fraudulent metrics/attestations for other agents (`submit_metrics`, `ingest_metrics`)

**Remediation:** Integrate `check_ownership_authorization()` into `require_tool()` or call it in each v1 route handler before invoking the tool function. The function already exists and works correctly — it simply isn't wired into the new routing path.

```python
# In gateway/src/deps/tool_context.py, after scope check:
from gateway.src.authorization import check_ownership_authorization

# Build params dict from request for ownership check
authz_result = check_ownership_authorization(agent_id, agent_tier, params, tool_name=tool_name)
if authz_result is not None:
    status, message, code = authz_result
    resp = await error_response(status, message, code, request=request)
    raise _ResponseError(resp)
```

---

#### 2. Stripe Webhook Replay — In-Memory Deduplication
**Severity:** CRITICAL
**File:** `gateway/src/stripe_checkout.py:31–32, 204–239`

**Issue:** Stripe session deduplication uses `_processed_sessions: set[str]` — an in-memory set lost on restart. After restart, Stripe retries cause duplicate credit deposits.

**Remediation:** Move to database-backed deduplication (e.g., `processed_stripe_sessions` table with `session_id` unique constraint).

---

#### 3. Refund Double-Spend Race Condition
**Severity:** CRITICAL
**File:** `products/payments/src/engine.py:252–333`

**Issue:** Refund validation reads `total_refunded`, checks remaining balance, then executes two separate wallet operations (withdraw from payee, deposit to payer) — all without a transaction wrapper. Concurrent refund requests can both pass validation and double-refund.

**Remediation:** Wrap the entire refund flow (validation + wallet ops + status update) in a single `BEGIN IMMEDIATE` transaction, matching the pattern already used by `convert_currency` in `products/billing/src/wallet.py:294`.

---

#### 4. X402 Nonces Stored In-Memory Only
**Severity:** CRITICAL
**File:** `gateway/src/x402.py:137–184`

**Issue:** X402 payment nonces use `self._used_nonces: set[str]` (in-memory), lost on restart. Additionally, check-then-mark is not atomic (race window between check at line 184 and mark in `routes/execute.py`).

**Remediation:** Move nonces to database with atomic INSERT-or-fail pattern. Add nonce expiration cleanup.

---

#### 5. Identity Metrics Write Without Ownership Check
**Severity:** CRITICAL
**File:** `gateway/src/tools/identity.py:32–45, 177–186`

**Issue:** `_submit_metrics()` and `_ingest_metrics()` accept arbitrary `agent_id` without verifying caller ownership. Agent A can submit fraudulent reputation data for Agent B.

**Remediation:** Add explicit ownership check in these tool functions:
```python
if tier != ADMIN_TIER and caller != target_agent:
    raise ToolForbiddenError(f"Cannot submit metrics for agent '{target_agent}'")
```

---

### P1 — Fix This Sprint (High)

#### 6. Stripe Webhook Timestamp Not Validated
**Severity:** HIGH
**File:** `gateway/src/stripe_checkout.py:54–72`

**Issue:** HMAC signature is verified but the `timestamp` component is parsed and never checked for staleness. Old validly-signed webhooks can be replayed indefinitely.

**Remediation:** Add timestamp freshness check (reject if |now - timestamp| > 300 seconds).

---

#### 7. Missing Idempotency on Critical Financial Endpoints
**Severity:** HIGH
**File:** `gateway/src/tools/payments.py`

**Issue:** `capture_intent`, `release_escrow`, `refund_intent`, `cancel_escrow` move funds but do not support idempotency keys. Network retries can cause double-capture or double-release.

**Remediation:** Add idempotency key support to these endpoints, matching the pattern used by `create_intent` and `deposit`.

---

#### 8. Float Precision Loss in Payment Responses
**Severity:** HIGH
**File:** `gateway/src/tools/payments.py` (lines 62, 75, 95, 109, 126, 142, 166)

**Issue:** Payment amounts stored as `Decimal` are returned as `float` in API responses. This causes precision loss for high-value or crypto-denominated transactions.

**Remediation:** Return amounts as strings (matching billing module's `CurrencyAmount` serializer pattern).

---

#### 9. Authenticated Requests Not Logged to Audit Trail
**Severity:** HIGH
**File:** `gateway/src/routes/execute.py:495–500`

**Issue:** Only admin-only tool executions are logged. Regular tool calls (including financial operations) have no audit trail beyond billing records.

**Remediation:** Log all tool executions with agent_id, tool_name, cost, outcome. Required for SOC 2 / PCI-DSS compliance.

---

#### 10. No Anomaly Detection Alerts for Auth Failures
**Severity:** HIGH
**File:** `monitoring/prometheus/alerts.yml`

**Issue:** Monitoring only alerts on generic error rate, latency, and downtime. No alerts for 401/403 spikes, rate limit violations, or unusual transaction volumes.

**Remediation:** Add Prometheus metrics and alerts for `a2a_auth_failures_total`, `a2a_rate_limit_exceeded_total`, and payment volume anomalies.

---

#### 11. CORS Allows Wildcard Methods/Headers
**Severity:** HIGH
**File:** `gateway/src/app.py:162–170`

**Issue:** When `CORS_ALLOWED_ORIGINS` is set, `allow_methods=["*"]` and `allow_headers=["*"]` are overly permissive.

**Remediation:** Restrict to `allow_methods=["GET", "POST", "OPTIONS"]` and explicit header whitelist.

---

#### 12. Weak TLS Cipher Suite in Nginx
**Severity:** HIGH
**Files:** `package/a2a-gateway-test/etc/nginx/sites-available/a2a-test:20–22`, `package/a2a-gateway-sandbox/etc/nginx/sites-available/a2a-sandbox:20–22`

**Issue:** `ssl_ciphers HIGH:!aNULL:!MD5` is too broad. Includes non-AEAD ciphers.

**Remediation:** Use explicit AEAD-only cipher list: `ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:...`

---

#### 13. Backup Encryption Keys Stored Plaintext on Disk
**Severity:** HIGH
**File:** `gateway/src/tools/infrastructure.py:355–364`

**Issue:** Backup encryption keys written to `backup_keys/{key_id}.key` as plaintext (0o600 perms). Filesystem compromise exposes all keys.

**Remediation:** Encrypt backup keys using a master key from environment variable or KMS before writing to disk.

---

#### 14. SQLite Database File Permissions Not Enforced
**Severity:** HIGH
**File:** `Dockerfile:66`, application startup

**Issue:** DB files created with default umask (potentially world-readable). No explicit `os.chmod(path, 0o600)` after creation.

**Remediation:** Set explicit 0o600 permissions on all DB files at initialization.

---

#### 15. Cryptography Package Not Pinned
**Severity:** HIGH
**File:** `Dockerfile:49`, `requirements.txt:8`

**Issue:** `cryptography>=46.0.6` allows unbounded upgrades including potentially vulnerable future versions.

**Remediation:** Pin to `cryptography>=46.0.6,<47.0`.

---

#### 16. HSTS Missing `preload` Directive
**Severity:** HIGH
**File:** `gateway/src/middleware.py:61`

**Issue:** HSTS header uses `max-age=31536000; includeSubDomains` but lacks `preload`.

**Remediation:** Add `; preload` and submit domain to hstspreload.org.

---

#### 17. Key Rotation Not Atomic
**Severity:** HIGH
**File:** `gateway/src/tools/infrastructure.py:193–208`

**Issue:** `_rotate_key()` revokes old key and creates new key as separate database operations. Crash between operations leaves agent with no valid key.

**Remediation:** Wrap in single database transaction.

---

### P2 — Fix Next Sprint (Medium)

#### 18. Webhook Secrets Stored Plaintext in DB
**Severity:** MEDIUM
**File:** `gateway/src/webhooks.py:33`

**Remediation:** Hash webhook secrets before storage; use hash for HMAC comparison.

---

#### 19. `/v1/execute` Params Accept Extra Fields
**Severity:** MEDIUM
**File:** `gateway/src/routes/execute.py:37`

**Issue:** The `params: dict[str, Any]` field accepts arbitrary keys. While JSON Schema validation mitigates this, `additionalProperties: false` is not enforced in catalog schemas.

**Remediation:** Document as intentional design or add `additionalProperties: false` to tool schemas.

---

#### 20. API Key Revocation Lacks Timestamp
**Severity:** MEDIUM
**File:** `products/paywall/src/storage.py:209–216`

**Issue:** `revoked` is a boolean flag with no timestamp. Audit trail lacks "when" of revocation.

**Remediation:** Add `revoked_at REAL` column to `api_keys` table.

---

#### 21. No API Key Rotation Policy/Expiration Enforcement
**Severity:** MEDIUM
**File:** `gateway/src/tools/infrastructure.py:193`

**Issue:** No enforced key rotation schedule. Keys can live indefinitely.

**Remediation:** Track creation timestamp; warn/reject keys older than 90 days.

---

#### 22. Balance Check Not Atomic with Charge
**Severity:** MEDIUM
**File:** `gateway/src/deps/billing.py:34–42`

**Issue:** Balance is checked in one query; charge happens in a separate call. Concurrent requests can both pass the balance check.

**Mitigation:** Wallet storage already uses atomic `balance >= ?` guards (`products/billing/src/storage.py:310–320`), so the practical risk is low. Document the dual-check design.

---

#### 23. Gateway Dependencies Lack Upper Version Bounds
**Severity:** MEDIUM
**File:** `gateway/pyproject.toml:6–12`

**Issue:** `fastapi>=0.115`, `pydantic>=2.0` etc. allow untested major version upgrades.

**Remediation:** Add `<N.0` upper bounds.

---

#### 24. Nginx Missing Security Headers at Proxy Layer
**Severity:** MEDIUM
**Files:** Nginx site configs

**Issue:** Security headers only set in application middleware, not at nginx level. Direct IP access bypasses them.

**Remediation:** Add `add_header` directives to nginx configs (defense in depth).

---

#### 25. HTTP/2 Field Size Limits Not Set
**Severity:** MEDIUM
**Files:** Nginx site configs

**Remediation:** Add `http2_max_field_size 4k; http2_max_header_size 16k;`

---

#### 26. Stripe Metadata Type Safety
**Severity:** MEDIUM
**File:** `gateway/src/stripe_checkout.py:209–211`

**Issue:** Webhook metadata fields extracted without type validation. If Stripe schema changes, `agent_id` could be an object.

**Remediation:** Validate types before use or use Pydantic model for webhook payload.

---

#### 27. Backup Path Traversal Check Edge Case
**Severity:** MEDIUM
**File:** `gateway/src/tools/infrastructure.py:380–387`

**Issue:** `real_backup != backup_dir` condition allows restoring from the directory itself (not a file).

**Remediation:** Add `os.path.isfile(real_backup)` check and file extension whitelist (`.db`, `.db.enc`).

---

### P3 — Fix Later (Low)

#### 28. Metrics Endpoint Unprotected
**Severity:** LOW
**File:** `gateway/src/app.py:109–111`

**Issue:** `/v1/metrics` exposes Prometheus metrics without authentication.

**Remediation:** Restrict to trusted IPs at nginx level.

---

#### 29. API Key Error Message May Leak Key Material
**Severity:** LOW
**File:** `gateway/src/routes/execute.py:284–286`

**Issue:** If `validate_key()` includes the key in exception messages, it could leak via error responses.

**Remediation:** Verify exception messages don't contain raw keys; wrap with generic error.

---

#### 30. Admin Audit Log Not Tamper-Proof
**Severity:** LOW
**File:** `gateway/src/admin_audit.py`

**Issue:** Audit logs in SQLite can be modified if DB is compromised.

**Remediation:** Consider hash chaining or write-once storage for compliance.

---

#### 31. Docker Image Lacks Read-Only Root Filesystem
**Severity:** LOW
**File:** `Dockerfile`

**Issue:** SQLite requires writable dirs, but non-DB paths should be read-only.

**Remediation:** Enable `read_only: true` in docker-compose with explicit writable tmpfs.

---

#### 32. Signing Key (HMAC Fallback) Not Persisted
**Severity:** LOW
**File:** `gateway/src/signing.py:59`

**Issue:** HMAC-SHA3-256 fallback key is generated fresh per restart. Old signatures become unverifiable.

**Remediation:** Store key in database or config for persistence (if verification across restarts is needed).

---

## Positive Findings (No Issues)

| Area | Status | Evidence |
|------|--------|----------|
| API Key Entropy | ✅ SECURE | `secrets.token_hex(12)` — 96-bit entropy (`paywall/src/keys.py:49`) |
| Key Hashing | ✅ SECURE | SHA3-256 (`paywall/src/keys.py:44`) |
| Input Validation | ✅ SECURE | All 36+ request models use `extra="forbid"` |
| SQL Injection | ✅ SECURE | All queries parameterized; `pg_execute` uses SQL validator |
| Command Injection | ✅ SECURE | No `os.system`/`eval`/`exec`; subprocess uses `create_subprocess_exec` |
| SSRF | ✅ SECURE | URL validator blocks private IPs, localhost, cloud metadata (`url_validator.py`) |
| Path Traversal | ✅ SECURE | `os.path.realpath()` + prefix check in backup/restore |
| Security Headers | ✅ SECURE | X-Content-Type-Options, X-Frame-Options, HSTS, CSP |
| Body Size Limit | ✅ SECURE | 1 MB limit via `BodySizeLimitMiddleware` |
| Request Timeout | ✅ SECURE | 30s timeout via `RequestTimeoutMiddleware` |
| Rate Limiting | ✅ SECURE | IP-based (public) + per-agent (authenticated), two-tiered |
| Admin-Only Guards | ✅ SECURE | BFLA properly enforced for `resolve_dispute`, `freeze_wallet`, etc. |
| Tier Escalation | ✅ SECURE | `_create_api_key` prevents creating keys above caller's tier |
| Scope Hierarchy | ✅ SECURE | read ⊂ write ⊂ admin; enforced via `ScopeChecker` |
| Webhook Signing | ✅ SECURE | HMAC-SHA256 with constant-time comparison |
| Identity Crypto | ✅ SECURE | Ed25519 keypairs via `cryptography` package |
| Post-Quantum Readiness | ✅ SECURE | CRYSTALS-Dilithium with HMAC-SHA3-256 fallback |
| PII Sanitization | ✅ SECURE | Admin audit log redacts secrets, strips `_caller_*` fields |
| Correlation IDs | ✅ SECURE | UUID per request, propagated to logs and responses |
| Wallet Atomicity | ✅ SECURE | `UPDATE ... WHERE balance >= ?` pattern in storage |
| Key Revocation | ✅ SECURE | Checked at every validation; instant enforcement |
| Key Expiration | ✅ SECURE | TTL support with `expires_at` field |

---

## Audit Checklist Status

### 1. Edge Security & Infrastructure
- [ ] **Bypass Prevention:** Cannot verify from source — requires infrastructure audit
- [ ] **DDoS Protection:** Cloudflare config not in codebase — requires infra audit
- [x] **WAF Configuration:** Application-level input validation is comprehensive (Pydantic, JSON Schema)
- [x] **TLS Configuration:** TLSv1.2/1.3 enforced in nginx; cipher suite needs hardening (#12)

### 2. Agent Authentication & Identity
- [x] **Credential Management:** Strong entropy, SHA3-256 hashing ✅
- [ ] **Advanced Auth (mTLS):** Not implemented — evaluate feasibility
- [x] **Token Security:** No JWT; stateful API keys are appropriate ✅
- [x] **Revocation:** Instant via soft-delete; needs timestamp (#20)

### 3. Authorization & Access Control
- [ ] **BOLA:** CRITICAL — v1 routers lack ownership checks (#1) ❌
- [x] **BFLA:** Admin-only tools properly guarded ✅
- [x] **Least Privilege:** Scope hierarchy enforced ✅

### 4. Business Logic & Financial Integrity
- [ ] **Race Conditions:** CRITICAL — refund double-spend (#3), nonce replay (#4) ❌
- [x] **Idempotency:** Supported on creation endpoints; missing on capture/release (#7)
- [x] **Webhook Security:** HMAC-SHA256 outbound signing ✅; Stripe inbound needs timestamp (#6)
- [ ] **Replay Attacks:** X402 nonces in-memory only (#4) ❌

### 5. Data Validation & Injection
- [x] **Strict Schema Validation:** All models `extra="forbid"` ✅
- [x] **Payload Limits:** 1 MB enforced ✅
- [x] **Injection Flaws:** SQL, command, SSRF all protected ✅

### 6. Observability & Auditing
- [ ] **Immutable Logging:** Only admin tools logged; needs full audit trail (#9) ❌
- [x] **PII/Sensitive Data:** Properly sanitized in audit logs ✅
- [ ] **Alerting:** No auth failure or transaction anomaly alerts (#10) ❌

---

## Remediation Timeline

| Phase | Items | Effort | Deadline |
|-------|-------|--------|----------|
| **P0 (Critical)** | #1–5 | 3–5 days | Before any production traffic |
| **P1 (High)** | #6–17 | 5–7 days | This sprint |
| **P2 (Medium)** | #18–27 | 3–5 days | Next sprint |
| **P3 (Low)** | #28–32 | 2–3 days | Next quarter |
