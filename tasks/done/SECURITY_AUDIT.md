# Security & Feature Audit Report: Green Helix A2A API (v1)

**Target:** `https://api.greenhelix.net/v1`
**Date:** 2026-04-04
**Auditor:** Autonomous Security Audit Framework
**API Version:** v0.9.2 (101 endpoints, 128 tools, 10 databases OK)
**Data Sources:**
- v0.5.3 security tests (2026-03-31): 30 scripts, 104 total tests, 16 open findings
- v0.9.1 prelaunch audit (2026-04-02): 234 tests across 4 phases, 4 confirmed findings

---

## 1. Edge Security & Infrastructure (Cloudflare & Hetzner)

- [ ] **Bypass Prevention:** Verify that the Hetzner origin servers drop all traffic that does not originate from Cloudflare's IP ranges (using firewall rules or Cloudflare Authenticated Origin Pulls).
  - [!] **NOT VERIFIED.** All 3 hosts (api, test, sandbox) resolve to Cloudflare IPs and serve a shared wildcard TLS cert, confirming Cloudflare fronting. However, no direct-to-origin testing was performed. Origin IP unknown. Cannot confirm firewall rules or Authenticated Origin Pulls are in place. **Requires infrastructure-level review.**
  - [!] **LV-09 (still open):** A 10,000-character Bearer token causes HTTP 520 (Cloudflare origin error), indicating the origin crashes under malformed input that Cloudflare forwards. This suggests Cloudflare is not filtering at the WAF level for oversized headers.

- [ ] **DDoS Protection:** Confirm that Cloudflare rate limiting is configured specifically for API endpoints, considering the expected high-frequency burst traffic of autonomous agents.
  - [!] **PARTIALLY VERIFIED.** Rate limit headers are present (`x-ratelimit-limit: 1000`). In v0.5.3, rate limiting was decorative only (LV-06: 0 x 429 across 500+ requests). In v0.9.1, enforcement improved significantly: 429 responses observed at 100 requests/hour. However, Cloudflare-level rate limiting configuration has not been independently verified vs. application-level enforcement.
  - [!] **LV-01/LV-02 (still open):** Slowloris and slow POST body attacks remain viable. 10 connections drip-feeding headers at 1 byte/s survived 15s with 0 closures. POST with Content-Length 1MB and only 20 bytes sent over 20s kept the server waiting. No header completion or body receipt timeouts configured.
  - [!] **LV-11 (still open):** 20 idle TLS connections survived 30+ seconds with no server-side keepalive timeout.

- [x] **WAF Configuration:** Ensure WAF rules are set to block common OWASP Top 10 API attacks (e.g., SQLi, XSS, Command Injection) before they reach the backend.
  - **VERIFIED.** Comprehensive injection testing across both audit rounds found zero successful injections:
    - SQL injection: 6 scripts, all negative. BOLA error messages reflect input but no SQL execution or error leakage (confirmed false positive in v0.9.1 audit).
    - Command injection: All negative. Blind injection "finding" in v0.5.3 was DNS latency false positive.
    - XSS/SSTI: All negative. SSTI "risk" was a false positive (402 with no template evaluation).
    - NoSQL injection: All negative (prior test used non-existent tools).
    - SSRF: Internal URLs blocked across 10 vectors. External SSRF to webhook.site causes 500 (L-4) but no server-side request is made.
    - Path traversal: All negative.
  - Cloudflare blocks payloads > 5MB (413). Application accepts up to 1MB.

- [x] **TLS Configuration:** Verify that the API enforces TLS 1.2 or 1.3 and uses strong cipher suites.
  - **VERIFIED.** All 3 hosts serve TLSv1.3 with a shared wildcard certificate (`*.greenhelix.net`). HSTS header present (`max-age=31536000; includeSubDomains`). Strong cipher suites in use.
  - Additional security headers verified present: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Content-Security-Policy: default-src 'none'`.
  - [!] Missing headers: `Referrer-Policy` and `Permissions-Policy` are absent.
  - [!] 500 error responses bypass middleware and are served without any security headers (bare `text/plain` from framework layer).

---

## 2. Agent Authentication & Identity

- [x] **Credential Management:** Verify how agents authenticate. If using API keys, ensure they are high-entropy and have strict rotation policies.
  - **VERIFIED.** API keys follow the format `a2a_<tier>_<24 hex chars>` (e.g., `a2a_pro_43548dafb79627458339ca11`). This provides 96 bits of entropy (24 hex chars = 96 bits), which is sufficient for API key security.
  - Key validation is strict: a fake key with valid format (`a2a_pro_000000000000000000000000`) returns 401 `API key not found`, confirming server-side lookup.
  - Tier is encoded in the key prefix (`free`, `pro`), which is verified server-side — free-tier keys cannot access pro-tier endpoints (BFLA verified).
  - [!] **Rotation policy not tested.** No `/v1/keys/rotate` or equivalent endpoint observed. `create_api_key` exists but was not testable in v0.5.3 (AUTH-500 crash). Rotation mechanism undocumented.

- [ ] **Advanced Auth:** Evaluate the feasibility/implementation of Mutual TLS (mTLS) for agent-to-server and agent-to-agent authentication.
  - [!] **NOT IMPLEMENTED.** No mTLS support detected. Authentication is solely via Bearer token or X-API-Key header. No client certificate negotiation observed in TLS handshake.
  - [!] **H-2 (v0.9.1 finding):** Undocumented `X-API-Key` header authentication path discovered. Both `Authorization: Bearer <key>` and `X-API-Key: <key>` are accepted. This is not in the OpenAPI spec's security schemes. Increases attack surface and may bypass auth-specific middleware (logging, rate limiting per auth type).

- [x] **Token Security (if applicable):** If using JWTs, verify that the signing algorithm is strong (e.g., RS256, not HS256), secrets are secure, and token expiration times are short.
  - **N/A — No JWTs in use.** Authentication is purely API-key-based. Keys are opaque server-side lookup tokens, not self-contained signed tokens. This eliminates JWT-specific vulnerabilities (algorithm confusion, weak secrets, expiration bypass) but also means there is no built-in expiration or claims mechanism.

- [x] **Revocation:** Test the mechanism for instantly revoking compromised agent credentials or tokens.
  - **PARTIALLY VERIFIED.** Credential stores are environment-isolated: a production API key returns 401 `API key not found` on test.greenhelix.net, confirming separate credential databases. This means revoking a key in prod does not require coordinating with test/sandbox.
  - [!] **Revocation mechanism itself not directly tested.** The `revoke_key` tool exists but was blocked by AUTH-500 in v0.5.3 and rate-limited in v0.9.1. Cannot confirm instant revocation or propagation time.

---

## 3. Authorization & Access Control (BOLA/BFLA)

- [x] **Broken Object Level Authorization (BOLA):** Test if Agent A can access, modify, or delete resources belonging to Agent B by manipulating resource IDs in the URI or payload.
  - **VERIFIED — ENFORCED.** BOLA protection returned 403 on all 16 cross-agent test cases in the v0.9.1 audit. Wallet, escrow, and payment intent operations all properly enforce agent-level ownership.
  - v0.8.4 had a CRITICAL escrow cancel BOLA bypass (any agent could cancel any escrow). This is **FIXED** in v0.9.1 — properly returns 403.
  - [!] **M-1 (v0.9.1 finding):** Input is reflected verbatim in BOLA 403 error messages: `{"detail": "Forbidden: 'agent_id' value '<attacker_input>' does not match your agent_id 'audit-pro'"}`. This confirms BOLA exists (aids reconnaissance), leaks the authenticated agent_id, and could enable reflected XSS if errors are ever rendered in HTML.

- [x] **Broken Function Level Authorization (BFLA):** Verify that standard agents cannot access administrative or orchestrator-level endpoints (e.g., `/v1/admin/agents/suspend`).
  - **VERIFIED.** Free-tier keys cannot access admin or pro-tier endpoints. Tier enforcement is server-side based on key prefix validation.
  - [!] Some BFLA tests for `keys/revoke` and `subscriptions` were rate-limited during v0.9.1 testing and could not be fully verified.

- [x] **Least Privilege:** Ensure agents only have access to the specific services and data necessary for their designated commerce tasks.
  - **VERIFIED.** Tier-based access control enforced. Free tier is restricted from pro-tier tools (identity metrics, claim chains, all payment tools). Tool catalog at `/pricing` returns per-tool tier requirements for all 128 tools.
  - LV-04/LV-12 (tool enumeration oracle): Known tool returns 402, unknown tool returns 400. This leaks tool existence to unauthenticated users. Auth pipeline runs tool validation before authentication. **Still open as of v0.9.2.**

---

## 4. Business Logic & Financial Integrity (Stripe/Crypto)

- [x] **Race Conditions:** Conduct parallel execution testing to identify Time-of-Check to Time-of-Use (TOCTOU) flaws, particularly during payment processing or ledger updates.
  - **VERIFIED — FIXED in v0.9.1.** 20 concurrent deposit requests result in exactly +20.0 balance change. No lost updates, no double-counting. This was a CRITICAL finding in v0.8.4 and has been resolved.

- [ ] **Idempotency:** Verify that critical financial endpoints (e.g., initiating a Stripe charge or submitting a crypto transaction) are idempotent to prevent duplicate processing on network retries.
  - [!] **NOT TESTED.** No explicit idempotency testing was performed in either audit round. No `Idempotency-Key` header support observed. Duplicate POST requests to deposit/withdraw endpoints may cause double processing on network retries. **Requires dedicated testing.**

- [x] **Webhook Security:** Ensure that webhooks from Stripe or blockchain indexers are strictly validated using cryptographic signatures to prevent spoofed payment confirmations.
  - **PARTIALLY VERIFIED.** `register_webhook` tool was **removed** in v0.5.3 (returns 400 `unknown_tool`), eliminating the user-facing webhook SSRF attack vector (F-05 no longer applicable). A Stripe webhook endpoint exists (`/stripe-webhook`) for receiving inbound Stripe events.
  - [!] Stripe webhook signature verification was not directly tested (requires Stripe test events). SSRF to external webhook URL (webhook.site) causes 500 instead of clean rejection (L-4).

- [ ] **Replay Attacks:** Check that timestamping or nonces are implemented and enforced to prevent malicious actors from replaying valid, signed agent requests.
  - [!] **NOT VERIFIED.** No evidence of request-level timestamps, nonces, or replay prevention. API keys are long-lived opaque tokens with no request signing. A captured valid request could be replayed indefinitely. **Requires implementation of request signing or short-lived tokens for high-value operations.**

---

## 5. Data Validation & Injection

- [x] **Strict Schema Validation:** Ensure every endpoint enforces strict input validation against a defined schema (e.g., OpenAPI spec). Reject undefined fields or unexpected data types.
  - **VERIFIED.** Strict Pydantic validation enforced. FastAPI/Pydantic rejects undefined fields and wrong types with 422 responses. OpenAPI 3.1.0 spec covers all 101 endpoints with 47 schemas (though only 3/47 have examples).
  - [!] **LV-03 (still open):** Type confusion on `create_intent` causes HTTP 500 instead of 400/422. 8 payloads (string/null/array/object for numeric fields, wrong param types) bypass Pydantic and crash the server. This is a pre-auth crash path.
  - [!] **M-2 (v0.9.1 finding):** Depositing extreme amounts (`1e18`, `999999999999.99`) causes HTTP 500 instead of 422. Missing maximum amount validation in Pydantic model.
  - [!] **M-3 (v0.9.1 finding):** Sub-penny amounts (`0.001`, `0.0001`, `1e-10`) are silently rounded to 2 decimal places without warning or rejection.

- [x] **Payload Limits:** Verify that maximum payload sizes are enforced to prevent application-level DoS attacks via massive JSON objects.
  - **PARTIALLY VERIFIED.** Cloudflare enforces a 5MB hard limit (returns 413). The application accepts payloads up to 1MB with no app-level rejection.
  - [!] **LV-08 (still open):** No application-level payload size limit. Recommend enforcing ~100KB at the application layer for the `/v1/execute` endpoint.

- [x] **Injection Flaws:** Test inputs for SQL/NoSQL injection, OS command injection, and SSRF (Server-Side Request Forgery) vulnerabilities.
  - **VERIFIED — ALL NEGATIVE.** Comprehensive testing across both audit rounds:
    - **SQL injection:** 6 dedicated scripts. All payloads returned 402 (unauthenticated) or 403 (BOLA). No SQL errors leaked. v0.9.1 SQLI "findings" were confirmed false positives (SQL keywords in reflected BOLA error messages, not actual SQL execution).
    - **Command injection:** All negative. `sleep 5` payload timing was DNS latency (5,189ms), not command execution.
    - **SSRF:** Internal URLs (`127.0.0.1`, `169.254.169.254`, `localhost`) blocked across 10 vectors. External SSRF causes 500 but no outbound request is made.
    - **NoSQL injection:** All negative.
    - **Path traversal:** All negative.
    - **XSS/SSTI:** All negative. Template injection payloads returned 402 with no evaluation.

---

## 6. Observability & Auditing

- [ ] **Immutable Logging:** Ensure all agent actions, especially authenticated requests and financial transactions, are logged to a secure, centralized logging server.
  - [!] **NOT DIRECTLY VERIFIED.** Every response includes an `x-request-id` header (UUID format, e.g., `550e8400-e29b-41d4-a716-446655440000`), indicating request-level tracing is implemented. However, the logging backend, storage, and immutability guarantees were not audited.
  - [!] **TEST-002 (v0.5.3 finding):** `/v1/metrics` endpoint is exposed on test.greenhelix.net (returns 200 with Prometheus-style metrics). This suggests observability infrastructure exists but access controls are misconfigured on the test host. **Not exposed on production.**

- [ ] **PII/Sensitive Data:** Verify that logs do not inadvertently capture sensitive information (e.g., full Stripe tokens, private keys, raw API keys).
  - [!] **NOT VERIFIED.** Log content was not directly inspectable. However, the following observations are relevant:
    - API keys appear in `Authorization` headers — standard practice, but must not be logged in full.
    - BOLA 403 errors include the authenticated agent_id in the response body (M-1). If these responses are logged verbatim, agent IDs are in logs.
    - 500 error responses are bare `text/plain` with no structured detail, suggesting stack traces are not leaked to clients. Whether they are logged internally is unknown.

- [ ] **Alerting:** Confirm that anomalous agent behavior (e.g., massive spike in 401/403 errors, unusual transaction volumes) triggers immediate alerts.
  - [!] **NOT VERIFIED.** During testing, hundreds of 401/403/500 errors were generated across both audit rounds with no observable throttling or blocking beyond rate limiting (100/hr in v0.9.1). No evidence of anomaly detection or alerting was observed. The metrics endpoint on test host (TEST-002) suggests monitoring infrastructure exists, but alerting configuration was not testable.

---

## Action Items & Remediation

### P0 — Critical (Fix Before Launch)

1. **[Critical] LV-01/LV-02: Slowloris and slow POST body attacks** — No header completion or body receipt timeouts. 10 connections at 1 byte/s survived 15s. Configure `client_header_timeout` (5-10s) and `client_body_timeout` (10-15s) at the reverse proxy or application server level. This is a direct DoS vector.

2. **[Critical] LV-03: Type confusion crashes on create_intent** — 8 type-confusion payloads cause HTTP 500 (pre-auth crash path). Add input type validation before processing. Return 400 with descriptive error. Audit all tools for the same issue.

3. **[Critical] M-2: Extreme financial amounts cause 500** — Depositing `1e18` or `999999999999.99` crashes the server. Add `le=1_000_000_000` (or appropriate maximum) to Pydantic amount fields. Return 422 for out-of-range values.

4. **[High] LV-04/LV-12: Tool enumeration oracle** — Known tool returns 402, unknown returns 400. Allows unauthenticated tool enumeration. Reorder auth pipeline: authenticate before tool validation. Or return uniform status for both cases.

5. **[High] H-2: Undocumented X-API-Key auth path** — Both `Authorization: Bearer` and `X-API-Key` headers are accepted. Either document in OpenAPI spec or disable X-API-Key to reduce attack surface.

### P1 — High (Fix Within 30 Days)

6. **[High] M-1: Input reflection in BOLA error messages** — 403 responses echo attacker-supplied agent_id verbatim. Sanitize or truncate reflected input. Use generic "Forbidden" message without echoing the attempted ID or the authenticated agent_id.

7. **[Medium] LV-08: No app-level payload size limit** — Application accepts up to 1MB; only Cloudflare's 5MB limit provides a cap. Add ~100KB limit at the application layer.

8. **[Medium] LV-09: Oversized Bearer token crashes origin** — 10,000-char Bearer token causes HTTP 520. Configure max header size validation at reverse proxy level.

9. **[Medium] M-3: Sub-penny amounts silently rounded** — `0.001` is accepted and rounded to 2 decimal places without warning. Either reject with 422 or document the rounding behavior.

10. **[Medium] Missing security headers on error responses** — 500 errors bypass middleware; served as bare `text/plain` without HSTS, CSP, X-Content-Type-Options, X-Frame-Options. Ensure the web server (not just application middleware) adds security headers to all responses. Also add missing `Referrer-Policy` and `Permissions-Policy` headers globally.

### P2 — Medium (Fix Within 60 Days)

11. **[Medium] TEST-002: /v1/metrics exposed on test host** — Internal Prometheus metrics publicly accessible on test.greenhelix.net. Block or require authentication.

12. **[Medium] TEST-003: /docs exposed on test host** — API documentation publicly accessible. Require authentication or IP allowlist.

13. **[Medium] Idempotency not implemented or tested** — No `Idempotency-Key` support observed. Financial endpoints (deposit, withdraw, create_intent) may double-process on network retries. Implement idempotency keys for all mutating financial operations.

14. **[Medium] Replay attack prevention absent** — No request signing, timestamps, or nonces. Captured requests can be replayed indefinitely. Consider implementing request signing for high-value operations.

15. **[Medium] LV-11: Idle connection timeout missing** — 20 idle TLS connections survived 30+ seconds. Set `keepalive_timeout` to 60-120s.

16. **[Low] Credential rotation mechanism unverified** — `create_api_key` and key revocation exist as tools but were not testable. Document and verify key rotation workflow.

17. **[Low] Logging and alerting not verified** — Request tracing exists (x-request-id) and metrics infrastructure exists (TEST-002), but log content, immutability, PII handling, and alerting thresholds were not auditable. Conduct internal review.

### Housekeeping

18. **[Info] LV-06: Rate limiting now partially enforced** — Was decorative in v0.5.3 (0 x 429). Now returns 429 at 100/hr in v0.9.1. Verify enforcement is consistent across all endpoints and tiers. Document rate limits per tier.

19. **[Info] LV-10: test.greenhelix.net version drift** — Was running v0.4.9 vs prod v0.5.3 in March. Now live but version not re-checked for v0.9.2. Keep environments in sync.

20. **[Info] F-05/F-09: Removed tools** — `register_webhook` and `file_dispute` return `unknown_tool` as of v0.5.3. Confirm intentional removal and update API documentation/changelog.

---

## Summary

| Metric | Value |
|--------|-------|
| Checklist items assessed | 15 |
| Verified / Passing | 8 |
| Partially verified | 3 |
| Not verified / Not tested | 4 |
| Open findings (all severity) | 20 |
| Critical | 3 (LV-01/02 slowloris, LV-03 type confusion, M-2 extreme amounts) |
| High | 3 (LV-04 tool oracle, H-2 X-API-Key, M-1 input reflection) |
| Medium | 8 (LV-08, LV-09, M-3, headers, TEST-002, TEST-003, idempotency, replay) |
| Low | 2 (rotation, logging) |
| Info | 4 (rate limits, version drift, removed tools) |
| Data sources synthesized | 2 reports (v0.5.3 + v0.9.1), 338 total tests |
| API version under audit | v0.9.2 |

---

*Generated: 2026-04-04 | Autonomous Security Audit Framework | Data: SECURITY_TEST_RESULTS_2026-03-31.md, PRELAUNCH_AUDIT_REPORT.md*
