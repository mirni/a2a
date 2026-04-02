# Pre-Launch Audit Remediation

**Source:** `tasks/external/PRELAUNCH_AUDIT_REPORT.md`
**Date:** 2026-04-02
**Auditor:** External multi-persona test orchestrator (234 tests, ~600 HTTP requests)
**Verdict:** CONDITIONAL GO — launch with remediation plan

---

## Status of v0.8.4 Fixes

Cross-referenced against codebase — all confirmed:

| Finding | Status | Evidence |
|---------|--------|----------|
| Race condition (deposits) | FIXED | Verified by auditor: 20 concurrent deposits = exact +20.0 |
| Escrow cancel BOLA | FIXED | Verified by auditor: properly returns 403 |
| Rate limiting | FIXED | Verified by auditor: 429s observed at 100/hr |
| BFLA (revoke_key, process_due_subscriptions) | FIXED | Both in `ADMIN_ONLY_TOOLS` at `authorization.py:34-35` |
| Negative/zero amounts | FIXED | `Field(gt=0)` on DepositRequest/WithdrawRequest (`billing.py:50,57`) |
| Intent capture 500 | NEEDS VERIFICATION | Not testable by auditor due to rate limiting |

---

## P0 — Fix Before Launch (code changes)

### 1. Add max amount validation (M-2: HTTP 500 on huge amounts)
**Severity:** MEDIUM (causes 500)
**File:** `gateway/src/routes/v1/billing.py:50,57`
**Root cause:** `Field(gt=0)` has no upper bound. `1e18` passes Pydantic but overflows at the storage layer.
**Fix:** Add `Field(gt=0, le=1_000_000_000)` to both `DepositRequest.amount` and `WithdrawRequest.amount`.
**TDD:**
- Red: `POST /v1/billing/wallets/{id}/deposit` with `{"amount": 1e18}` -> expect 422
- Red: `POST /v1/billing/wallets/{id}/deposit` with `{"amount": 999999999999.99}` -> expect 422
- Green: Add `le=1_000_000_000` constraint

### 2. Sanitize BOLA error messages (M-1: input reflection)
**Severity:** MEDIUM (aids reconnaissance, potential XSS if rendered in HTML)
**File:** `gateway/src/authorization.py:102`
**Root cause:** `f"Forbidden: '{field}' value '{value}' does not match your agent_id '{caller_agent_id}'"` — echoes raw user input.
**Fix:** Truncate and sanitize `value`, or use generic message. Also avoid leaking the caller's real agent_id.
**Suggested replacement:**
```python
return (403, "Forbidden: you do not have access to this resource", "forbidden")
```
**TDD:**
- Red: Test BOLA 403 response does NOT contain the attacker-supplied agent_id
- Green: Replace error message

### 3. Fix webhook external URL 500 (L-4: SSRF)
**Severity:** LOW (causes 500, not a security bypass)
**File:** `gateway/src/webhooks.py:334`
**Root cause:** `_send()` only catches `httpx.HTTPError`. Other exceptions (`OSError`, `asyncio.TimeoutError`) propagate as 500.
**Fix:** Broaden exception handling in `_send()` to catch `Exception` and return graceful failure.
**TDD:**
- Red: Register webhook with unreachable external URL, trigger test -> expect non-500
- Green: Add broader exception handling

---

## P1 — Fix Soon After Launch (code changes)

### 4. Unify error format (L-3: inconsistent 422 errors)
**Severity:** LOW (DX issue)
**Root cause:** FastAPI's default `RequestValidationError` handler returns Pydantic format, not RFC 9457.
**Fix:** Add custom exception handler in `app.py`:
```python
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return await error_response(422, str(exc), "validation_error", request=request)
```
Also handle 405 Method Not Allowed similarly.

### 5. Document X-API-Key auth (H-2)
**Severity:** HIGH per auditor, but LOW risk (intentional, fully pipelined)
**Finding:** API accepts `X-API-Key` header alongside `Authorization: Bearer`.
**Status:** INTENTIONAL — implemented in `auth.py:12-29`, tested in `test_execute.py`, documented in onboarding endpoint, goes through same auth/rate-limit pipeline.
**Fix:** Add `X-API-Key` as a security scheme in the OpenAPI spec. No code changes needed.
**File:** `gateway/src/app.py` (OpenAPI metadata) or custom OpenAPI schema.

### 6. Sub-penny precision policy (M-3)
**Severity:** MEDIUM (silent rounding)
**Root cause:** `Decimal` amounts accepted with arbitrary precision, silently rounded via `credits_to_atomic()` (8 decimal places via `SCALE = 100_000_000`).
**Options:**
- A) Reject amounts with more than 2 decimal places at Pydantic level (`decimal_places=2`)
- B) Document the 8-decimal precision behavior
- C) Add `max_digits` and `decimal_places` to the Pydantic field
**Recommended:** Option A (reject > 2 dp) for billing endpoints, since the currency is CREDITS with cent-level precision.

---

## P2 — Operational / Non-Code Items

### 7. DNS latency investigation (H-1)
**Severity:** HIGH (p95 = 5,274ms)
**Root cause:** Cloudflare DNS intermittent ~5s timeout on upstream resolution. Not application-level.
**Actions:**
- [ ] Check Cloudflare DNS TTL for api.greenhelix.net
- [ ] Check if CNAME flattening is enabled
- [ ] Test from multiple regions
- [ ] Document connection pooling as required client behavior
- [ ] Consider keep-alive requirements in SDK documentation

### 8. Verify intent capture fix
**Action:** Manually re-test intent capture endpoint — auditor couldn't verify due to rate limiting.
```bash
curl -s -X POST -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"intent_id": "test", "amount": 10.0}' \
  https://api.greenhelix.net/v1/payments/intents/{id}/capture
```

---

## DX Improvements (60-90 day roadmap, not blocking)

These are feature requests from the marketing persona, not bugs:

- [ ] Add request/response examples to OpenAPI spec (only 3/47 schemas have examples)
- [ ] Self-service onboarding (`/v1/register` returns 400 on test payloads)
- [ ] Human-readable pricing/tiers page
- [ ] CORS support (OPTIONS returns 405)
- [ ] Transfer endpoint (`/v1/billing/wallets/{id}/transfer`)
- [ ] Status page with uptime monitoring
- [ ] API versioning strategy documentation
- [ ] Sandbox documentation (sandbox.greenhelix.net)
- [ ] Rate limit documentation per tier
- [ ] Connection pooling guide
- [ ] SDK documentation (Python SDK exists at `sdk/`, TS SDK at `sdk-ts/`)

---

## Summary

| Priority | Count | Effort | Description |
|----------|-------|--------|-------------|
| P0 (pre-launch) | 3 | ~2 hours | Max amount validation, BOLA sanitization, webhook error handling |
| P1 (post-launch) | 3 | ~3 hours | Error format, X-API-Key docs, sub-penny policy |
| P2 (ops) | 2 | ~1 day | DNS investigation, intent capture verification |
| DX backlog | 11 | Ongoing | Feature requests from marketing/DX audit |
