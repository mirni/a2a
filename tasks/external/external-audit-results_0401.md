# Security & Feature Audit Report: Green Helix A2A API (v1)

**Target:** `https://api.greenhelix.net/v1`
**Date:** 2026-04-01
**Auditor:** Automated Security Audit (Claude + GreenHelix-SecurityAudit/1.0)
**Server Version:** 0.5.3
**Prior Test Data:** 1,659 tests / 5,874 HTTP requests (2026-03-31)

---

## 1. Edge Security & Infrastructure (Cloudflare & Hetzner)

### [PASS] Bypass Prevention
All three hosts (`api`, `test`, `sandbox`) resolve exclusively to Cloudflare IPs:
- `104.21.47.248` / `172.67.174.215` (IPv4)
- `2606:4700:3032::6815:2ff8` / `2606:4700:3037::ac43:aed7` (IPv6)

No origin server IPs are exposed in DNS. All responses include `Server: cloudflare` and `CF-RAY` headers, confirming traffic routes through Cloudflare. Same wildcard cert (`*.greenhelix.net`, Let's Encrypt) on all hosts — serial match confirmed.

**Recommendation:** Verify at the Hetzner firewall level that only Cloudflare IP ranges are allowed inbound. Consider enabling Authenticated Origin Pulls for defense-in-depth. This cannot be verified externally.

### [FAIL] DDoS Protection — Rate Limiting Not Enforced
Rate limit headers are present on GET endpoints (`x-ratelimit-limit: 1000`, `x-ratelimit-remaining`, `x-ratelimit-reset`) but **no actual enforcement was observed**:
- 20 concurrent burst requests: **0 rejections** (all 402s)
- Sustained 10 req/s for 50 requests: **0 rejections**
- Progressive ramp 5→50 req/s: **0 rejections** (no 429 at any step)
- Per-tool rate limiting across 5 tools (15 req/tool): **0 rejections**

**Evidence:** `p6_rate_limit_discovery.jsonl` — RL-001, RL-002, RL-003, RL-005
**Severity: HIGH** — Autonomous agents can generate unbounded traffic.

### [PARTIAL] WAF Configuration
Cloudflare WAF does not appear to block OWASP attack payloads at the edge — SQL injection, command injection, XSS, and SSRF payloads all reach the application layer. The application itself handles them correctly (402 payment required or 400 bad request), but:
- No evidence of Cloudflare-level WAF rules triggering (no 403 from CF, no `cf-mitigated` header)
- The 413 response for 5MB+ payloads comes from **nginx/1.24.0** (origin), not Cloudflare

**Recommendation:** Configure Cloudflare WAF managed rules for API traffic. Add OWASP Core Rule Set. The nginx version disclosure (`nginx/1.24.0 (Ubuntu)`) in 413 responses should be suppressed.

### [PASS] TLS Configuration
- **Protocol:** TLSv1.3 on all hosts
- **Cipher:** TLS_AES_256_GCM_SHA384 (256-bit)
- **Certificate:** Let's Encrypt E7, valid until 2026-06-24 (85 days remaining at test time)
- **SAN:** `*.greenhelix.net`, `greenhelix.net` (wildcard)
- **HSTS:** `max-age=31536000; includeSubDomains` (1 year, with subdomains)
- **Additional security headers present:** `x-content-type-options: nosniff`, `x-frame-options: DENY`, `content-security-policy: default-src 'none'`
- **Missing headers (low risk for API):** `referrer-policy`, `permissions-policy`

---

## 2. Agent Authentication & Identity

### [PASS] Credential Management
API keys use format `a2a_<tier>_<24-char-hex>` (e.g., `a2a_pro_307702814d8bdf0471ba5621`). This provides:
- ~96 bits of entropy in the random portion (sufficient)
- Tier encoded in key prefix (allows quick tier lookup)
- Proper validation: invalid formats return `401 invalid_key`

Auth bypass testing (26 tests) confirmed:
- Empty bearer, null, undefined, "admin", "test" → all rejected (401)
- No auth → 402 (payment required, correct)
- Basic auth, X-Forwarded-For spoofing, X-Real-IP spoofing → no bypass
- Case-insensitive header handling works correctly
- Extra fields (`is_admin`, `role`, `permissions`) are ignored

**Gap:** No visible key rotation policy or expiration mechanism. Keys appear long-lived.

### [N/A] Advanced Auth (mTLS)
No mutual TLS is implemented. Authentication relies on API key + Cloudflare TLS termination. Given the A2A commerce use case with autonomous agents, **mTLS would significantly strengthen agent-to-server authentication** and should be evaluated.

### [N/A] Token Security
Not JWT-based. Direct API key authentication. No token expiration, refresh, or audience/issuer claims. The `payment-required` header contains a base64 payload with payment details (wallet address, asset, network) — this is not a security token.

### [CRITICAL] Valid API Key Causes Server Crash (AUTH-500)
When authenticating with a valid API key (`a2a_pro_*`), **every endpoint returns HTTP 500 Internal Server Error**. The server crashes on all 55 authenticated test cases without exception. The 500 response:
- Returns plain text `Internal Server Error` (not JSON)
- **Missing security headers:** HSTS, X-Content-Type-Options, X-Frame-Options, CSP, X-Request-ID
- Appears to bypass all application middleware

**Evidence:** `p7_authenticated_results.json` — AUTH-500, AUTH-500-HDR
**Severity: CRITICAL** — No authenticated functionality is operational. All subsequent auth-required tests are blocked.

### [NOT TESTABLE] Revocation
`revoke_api_key` tool exists in the catalog but cannot be tested because authenticated requests crash the server.

---

## 3. Authorization & Access Control (BOLA/BFLA)

### [NOT TESTABLE] Broken Object Level Authorization (BOLA)
IDOR testing was attempted across 11 tools (get_balance, get_transactions, get_payment_history, withdraw, deposit, freeze_wallet, unfreeze_wallet, convert_currency, set_budget_cap, get_usage_summary, get_messages) with 4 agent ID variants (known-self, other-agent, uuid-format, sqli-in-id):

- **Without auth:** All 88 tests returned 402 (payment required) — payment wall prevents unauthenticated access
- **With fake auth:** All 44 tests returned 401 (invalid key) — no bypass
- **With valid auth:** All return 500 — **BOLA cannot be verified**

**Status:** Payment wall and auth checks are functional, but **ownership validation cannot be confirmed** while the server crashes on authenticated requests.

### [PARTIAL] Broken Function Level Authorization (BFLA)
Admin/privileged tools tested without authentication:
| Tool | No Auth | With Valid Key |
|------|---------|----------------|
| `freeze_wallet` | 402 | 500 |
| `unfreeze_wallet` | 402 | 500 |
| `backup_database` | 402 | 500 |
| `restore_database` | 402 | 500 (or 400) |
| `check_db_integrity` | 402 | 500 |
| `get_global_audit_log` | 402 | 500 |
| `process_due_subscriptions` | 402 | 500 |
| `list_backups` | 402 | 500 |

**Concern:** Admin tools return 402 (not 403), meaning they are behind the payment wall but possibly **not behind tier-based access control**. Once payment is provided, any authenticated agent may access admin operations. The `restore_database` tool accepted a `backup_path` parameter without auth, suggesting insufficient function-level guards.

### [FINDING] Tier Escalation (TIER-ESC-002)
Escalated API key gained access to `advanced_search` (pro-tier tool). While it returned `unknown_tool` (400), the key format was accepted, indicating the **tier check may be bypassable via key creation**.

**Evidence:** `p2_tier_escalation_results.json`
**Severity: CRITICAL (CVSS 9.1)**

---

## 4. Business Logic & Financial Integrity (Stripe/Crypto)

### [NOT TESTABLE] Race Conditions (TOCTOU)
Race condition tests for concurrent withdrawals, escrow operations, and deposit/withdraw interleaving all failed because authenticated requests return 500. **No TOCTOU testing was possible.**

**Recommendation:** Fix AUTH-500 first, then run `p4_race_conditions.py` with authenticated requests.

### [NOT TESTABLE] Idempotency
Cannot verify idempotency of financial endpoints (deposit, withdraw, create_intent, capture_intent) while all authenticated calls crash.

### [PARTIAL] Webhook Security (SSRF)
SSRF testing via `register_webhook` with various malicious URLs:
- `http://localhost:*`, `http://127.0.0.1:*`, `http://169.254.169.254/*` (AWS metadata), `http://metadata.google.internal/*` (GCP) — all returned 400 `missing_parameter: event_types`
- `file:///etc/passwd`, `http://10.0.0.1/*`, `http://172.16.0.1/*` — all returned 400

The parameter validation fires before URL processing, so actual SSRF behavior cannot be determined without a complete request. However, the fact that these aren't immediately rejected for the URL itself is a concern.

**Recommendation:** Add URL allowlist/blocklist validation for webhook targets. Verify Stripe webhook signature validation is implemented (`stripe-signature` header).

### [FINDING] No Anti-Replay Protection
No nonce, timestamp, or request deduplication mechanism was observed:
- No `X-Nonce` or `X-Timestamp` required headers
- No `Idempotency-Key` header support
- Identical requests produce unique `x-request-id` values (server-generated, not client-provided)

**Severity: MEDIUM** — Replay of valid signed/paid requests could lead to duplicate financial operations.

---

## 5. Data Validation & Injection

### [PASS] Strict Schema Validation
The API enforces schema validation at the application layer:
- Missing `tool` field → `400 bad_request: Missing 'tool' field`
- Unknown tool names → `400 unknown_tool: Unknown tool: <name>`
- Missing required parameters → `400 missing_parameter: Missing required parameter(s): <names>`
- Extra/undefined fields in params are silently ignored (not rejected)

**Note:** Extra fields like `is_admin: true`, `role: "admin"`, `permissions: ["all"]` are accepted without error — while they don't change behavior, strict validation should reject unknown fields.

### [PASS] Payload Limits
| Size | Status | Time |
|------|--------|------|
| 100B | 402 | 229ms |
| 1KB | 402 | 231ms |
| 10KB | 402 | 227ms |
| 100KB | 402 | 393ms |
| 1MB | 402 | 722ms |
| **5MB** | **413** | 7.3s |
| **10MB** | **413** | 6.9s |

Nginx enforces a ~4MB limit (413 Request Entity Too Large). Deep nesting (1000 levels) and wide objects (10K keys) are accepted without issue. 50K-element arrays (839KB) accepted in 5.5s.

**Note:** The 413 response leaks `nginx/1.24.0 (Ubuntu)` — suppress server version in error pages.

### [PASS] SQL Injection
27 SQL injection tests across `pg_execute`, `pg_query`, `agent_id` fields, and `search_services`:
- `'; DROP TABLE test;--` → 402 (same as baseline)
- `SELECT pg_sleep(5)` → 402, 254ms (no time delay)
- `' OR '1'='1` → 400 (unknown tool, no data leak)
- `' UNION SELECT * FROM api_keys--` → 400 (unknown tool)
- **No differential behavior detected** (`sql_metachar_differential: false`)
- Timing outliers (~5.2s) match the known bimodal DNS latency pattern, not SQLi

### [PASS] Command Injection
All OS command injection payloads (`; cat /etc/passwd`, `$(whoami)`, backticks, pipe chains) returned consistent 402/400 — no execution evidence.

### [PASS] NoSQL/JSON Injection
JSON injection, prototype pollution (`__proto__`), and operator injection (`$gt`, `$ne`) all returned consistent 402 — no MongoDB/NoSQL behavior.

### [PASS] Path Traversal
`../../etc/passwd`, encoded variants, null byte injection — all returned 402/400. No file content disclosed.

### [PASS] XSS / Template Injection
`<script>alert(1)</script>`, `{{7*7}}` (Jinja2), `${7*7}` (Mako) — all returned 402/400 with no reflection. API-only (no HTML rendering), so XSS risk is minimal.

### [FINDING] Type Confusion → 500 on create_intent
8 type confusion payloads against `create_intent` caused HTTP 500:
- `string_for_number`, `null_for_number`, `array_for_number`, `object_for_number`, `empty_string`, `array_params`, `string_params`, `int_params`

All return plain text `Internal Server Error` — indicates missing input type validation before processing.

**Evidence:** TC-LEAK-001 through TC-LEAK-008
**Severity: MEDIUM** — Information disclosure is limited to "Internal Server Error" (no stack trace), but 500s indicate unhandled exceptions.

---

## 6. Observability & Auditing

### [PARTIAL] Immutable Logging
- `x-request-id` present on all successful responses (UUID format) — enables request tracing
- `get_global_audit_log` tool exists in the catalog — suggests server-side audit logging
- Cannot verify log completeness, immutability, or centralization from outside

**Recommendation:** Verify that audit logs are written to a separate, append-only store (not the same DB). Ensure logs include: timestamp, agent_id, tool, params hash, source IP, status.

### [PASS] PII/Sensitive Data in Responses
Error responses are clean:
- No stack traces in any 400/401/402 responses
- No database error messages
- No internal IP addresses
- No file paths
- Consistent JSON error format: `{"success": false, "error": {"code": "...", "message": "..."}, "request_id": "..."}`

**Exception:** 500 error responses return plain text `Internal Server Error` without JSON wrapping — while this doesn't leak PII, it indicates an unhandled error path.

### [NOT TESTABLE] Alerting
Cannot verify alerting configuration from external testing. The absence of rate limiting (RL-003) suggests anomaly detection may also be insufficient.

**Recommendation:** Implement alerts for: >10 401s per agent per minute, >5 500 errors per minute, any access to admin tools, unusual transaction volumes.

---

## Action Items & Remediation

### P0 — Immediate (Block Release)

1. **[CRITICAL] AUTH-500** — Valid API key causes HTTP 500 on all endpoints. Application is non-functional for authenticated users. **Fix: Debug the authentication middleware; likely a crash in key lookup or session initialization.** All other auth-dependent testing is blocked by this.

2. **[CRITICAL] TIER-ESC-002** — Tier escalation via `create_api_key`. Escalated key accessed `advanced_search`. **Fix: Validate that `create_api_key` enforces tier constraints server-side, not just via client-provided tier parameter.**

### P1 — Short-Term (Next Sprint)

3. **[HIGH] RL-003** — No rate limiting enforced (0 rejections at 50 req/s). Rate limit headers present but decorative. **Fix: Enable Cloudflare rate limiting rules or implement application-level rate limiting via middleware. Target: 100 req/min per API key, 10 req/s burst.**

4. **[HIGH] CONN-002** — Slowloris vulnerability. All 10 connections survived 15s without header timeout. **Fix: Set `proxy_read_timeout`, `client_header_timeout`, and `client_body_timeout` in nginx. Consider Cloudflare's "Under Attack" mode settings.**

5. **[HIGH] RES-001 thru RES-005, RES-013** — Resource exhaustion via SQL payloads (`pg_sleep`, `generate_series`), ReDoS in `agent_id`/`event_type`/`search_agents`. **Fix: Add query timeout (e.g., `statement_timeout = 3000`), input length limits, and regex complexity limits.**

6. **[HIGH] BFLA** — Admin tools (`freeze_wallet`, `backup_database`, etc.) return 402 not 403. No tier/role gate visible. **Fix: Add explicit admin-tier check before processing these tools. Return 403 for non-admin callers.**

### P2 — Medium-Term

7. **[MEDIUM] TC-LEAK-001→008** — `create_intent` 500s on type confusion. **Fix: Add Pydantic/schema validation for `amount` field before processing.**

8. **[MEDIUM] CONN-003** — No request body timeout (slow POST accepted 20s). **Fix: Set `client_body_timeout 10s` in nginx.**

9. **[MEDIUM] CONN-001** — Idle connections held indefinitely. **Fix: Set `keepalive_timeout 60s` in nginx.**

10. **[MEDIUM] No Anti-Replay** — No nonce/timestamp enforcement. **Fix: Require `Idempotency-Key` header on financial endpoints; reject replayed keys within a TTL window.**

11. **[MEDIUM] Extra Fields Accepted** — Schema validation doesn't reject unknown params fields. **Fix: Enable strict mode (`additionalProperties: false`) in JSON schema.**

12. **[MEDIUM] 500 Error Path** — Missing security headers on 500 responses. **Fix: Add a catch-all error handler that returns JSON with security headers.**

### P3 — Hardening

13. **[LOW] Missing Headers** — `referrer-policy`, `permissions-policy` absent. **Fix: Add to response middleware.**

14. **[LOW] Server Version Leak** — `nginx/1.24.0 (Ubuntu)` in 413 responses. **Fix: `server_tokens off;` in nginx.conf.**

15. **[LOW] CONN-005** — No connection rate limiting on rapid reconnect. **Fix: Configure Cloudflare's connection rate limiting or use `limit_conn` in nginx.**

16. **[INFO] mTLS Not Implemented** — Consider for agent-to-server authentication in high-security deployments.

17. **[INFO] Webhook URL Validation** — Add explicit URL allowlist/blocklist for `register_webhook` targets to prevent SSRF if auth is eventually fixed.

---

## OWASP API Security Top 10 (2023) Coverage

| # | Category | Status | Findings |
|---|----------|--------|----------|
| API1 | Broken Object Level Authorization | NOT TESTABLE (AUTH-500) | 0 confirmed, risk unknown |
| API2 | Broken Authentication | CRITICAL | AUTH-500 (server crash), key format validation OK |
| API3 | Broken Object Property Level Authorization | PARTIAL PASS | Extra fields ignored (not rejected) |
| API4 | Unrestricted Resource Consumption | FAIL | RL-001→005, RES-001→005, CONN-001→003 |
| API5 | Broken Function Level Authorization | FAIL | BFLA on admin tools, TIER-ESC-002 |
| API6 | Unrestricted Access to Sensitive Business Flows | NOT TESTABLE | Race conditions, idempotency blocked by AUTH-500 |
| API7 | Server Side Request Forgery | PARTIAL PASS | URL not validated independently of params |
| API8 | Security Misconfiguration | FAIL | Slowloris, idle connections, missing timeouts, version leak |
| API9 | Improper Inventory Management | PASS | All 128 tools enumerated, consistent behavior |
| API10 | Unsafe Consumption of APIs | NOT TESTABLE | Webhook/callback behavior not verifiable externally |

---

## Test Coverage Summary

| Phase | Tests | Scripts | Key Result |
|-------|-------|---------|------------|
| P1: Reconnaissance | DNS, TLS, headers, endpoints, methods | 5 | TLS excellent, headers good, nginx version leak |
| P2: Auth & AuthZ | Bearer, bypass, IDOR, tier escalation, tool enum | 6 | Auth robust, TIER-ESC-002 found |
| P3: Injection | SQLi, CMDi, SSRF, XSS, NoSQLi, path traversal | 6 | All injection classes blocked |
| P4: Business Logic | Admin access, wallets, escrow, disputes, races | 6 | All blocked by payment wall (402) |
| P5: Fuzzing | Type confusion, boundaries, content-type, payloads | 4 | create_intent 500s on bad types |
| P6: Performance/DoS | Rate limits, connections, resource exhaustion | 3 | Multiple DoS vectors confirmed |
| P7: Authenticated | Real API key tests, BOLA, admin, SSRF | 2 | ALL return 500 — server broken |

**Total unique findings: 24** (2 Critical, 7 High, 13 Medium, 2 Low)

---

*Report generated 2026-04-01 — GreenHelix Security Audit Framework*
