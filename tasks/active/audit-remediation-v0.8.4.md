# Audit Remediation Plan — v0.8.4 External Security Audit

**Source:** `tasks/external/external-audit-results.v0.8.4.md`
**Date:** 2026-04-02
**Findings:** 12 total (6 CRITICAL, 2 HIGH, 4 MEDIUM)

---

## P0 — Critical (Code Fixes)

### 1. BFLA — Admin endpoints accessible to non-admin keys (3 findings)
**IDs:** BFLA-PROCESS_SUBS-PRO, BFLA-REVOKE_KEY-FREE, BFLA-REVOKE_KEY-PRO

**Root cause:** `process_due_subscriptions` and `revoke_api_key` missing from `ADMIN_ONLY_TOOLS` in `gateway/src/authorization.py`.

**Fix:** Add both tool names to the `ADMIN_ONLY_TOOLS` frozenset.

**TDD:**
- Red: test pro key → `POST /v1/payments/subscriptions/process-due` → expect 403
- Red: test free key → `POST /v1/infra/keys/revoke` → expect 403
- Green: add to `ADMIN_ONLY_TOOLS`

### 2. ESCROW-CANCEL-BOLA — Non-payer can cancel escrow
**ID:** ESCROW-CANCEL-BOLA

**Root cause:** The route handler's `check_ownership()` call is ineffective — `escrow_id` is not in `OWNERSHIP_FIELDS`. The tool function `_cancel_escrow` has `_check_escrow_ownership()` which should block it, but audit shows it doesn't. Need to investigate and test.

**Fix:** Verify/fix `_check_escrow_ownership` in `gateway/src/tools/payments.py`. May need to add escrow-aware ownership check at the route level.

**TDD:**
- Red: test free agent cancels pro's escrow → expect 403
- Green: fix ownership enforcement

### 3. RACE-DEP — Race condition on concurrent deposits
**ID:** RACE-DEP

**Root cause:** Wallet deposit/withdraw operations may have a read-then-write race under concurrent HTTP requests. Even though `atomic_credit` uses `UPDATE SET balance = balance + ?`, the concurrent request handling may cause lost updates depending on transaction isolation.

**Fix:** Ensure wallet operations use `BEGIN IMMEDIATE` for write serialization, or use a single atomic UPDATE with RETURNING pattern. Need to trace the actual deposit code path from the REST endpoint to storage.

**TDD:**
- Red: test concurrent deposits (asyncio.gather) → assert final balance matches expected
- Green: fix serialization

### 4. INTENT-CAPTURE-500 — Intent capture crashes
**ID:** INTENT-CAPTURE-500

**Root cause:** `_capture_intent` in `gateway/src/tools/payments.py` calls `ctx.payment_engine.capture()` which can raise `InsufficientCreditsError` or `WalletNotFoundError` from the billing layer. The route has `handle_product_exception()` but it may not map billing exceptions.

**Fix:** Either catch billing exceptions in `_capture_intent` and re-raise as tool errors, or add billing exception mappings to `handle_product_exception()`.

**TDD:**
- Red: test capture by owner → expect 200
- Red: test capture by non-owner → expect 403
- Green: add error handling/mapping

---

## P1 — High (Code Fixes)

### 5. AMT-500 — Negative/zero amounts cause 500
**IDs:** AMT-500-NEGATIVE, AMT-500-NEGATIVE_SMALL, AMT-500-ZERO

**Root cause:** `DepositRequest` and `WithdrawRequest` models in `gateway/src/routes/v1/billing.py` have `amount: Decimal` without `gt=0` constraint. Negative/zero amounts pass Pydantic validation but crash in business logic.

**Fix:** Add `Field(gt=0)` to amount fields in both models.

**TDD:**
- Red: test deposit amount=-100 → expect 422
- Red: test deposit amount=0 → expect 422
- Green: add `Field(gt=0)`

### 6. RL-BURST/SUSTAINED — Rate limiting not enforced
**IDs:** RL-BURST-30, RL-SUSTAINED

**Root cause:** Rate limit check happens BEFORE recording the event. Under concurrent load, all requests read the same count and pass. Recording happens after tool execution.

**Fix:** Record the rate event BEFORE executing the tool (atomic increment-then-check), or use a semaphore. Consider `INSERT + SELECT COUNT` in a single transaction.

**TDD:**
- Red: test N concurrent requests → expect some 429s
- Green: implement atomic rate check

---

## P2 — Ops / Manual (No code changes)

### 7. AUTH-OLD-KEY — Old API key still accepted
**ID:** AUTH-OLD-KEY

This is an ops task, not a code bug. The old key `a2a_pro_307702814d8bdf0471ba5621` from a previous deployment is still in the paywall DB.

**Action:** SSH to server and run:
```bash
sqlite3 /var/lib/a2a/paywall.db "DELETE FROM api_keys WHERE key_hash NOT IN (SELECT key_hash FROM api_keys ORDER BY created_at DESC LIMIT 20);"
```
Or use the now-working `revoke_api_key` endpoint (after BFLA fix) to revoke old keys.

### 8. Rate limit value drift (1000 → 10000)
**ID:** RL-DRIFT (informational)

`x-ratelimit-limit` changed from 1000 to 10000 mid-audit. Investigate whether tier config was changed during the session or if the audit hit a different key tier.

**Action:** Check tier configs in `gateway/src/deps/rate_limit.py` — likely the audit switched from free (1000/hr) to pro (10000/hr) key.

### 9. Key creation returns 403 for enterprise
**ID:** KEY-CREATE-403 (informational)

`POST /v1/infra/keys` returns 403 even for enterprise tier. Verify this is intentional — admin key creation may require a separate mechanism.

**Action:** Check `create_api_key` in catalog.json for tier_required. If intentional, document it.

---

## Implementation Order

1. **P0 items 1+2** (BFLA + BOLA) — authorization fixes, smallest blast radius
2. **P0 item 4** (INTENT-CAPTURE-500) — error handling fix
3. **P1 item 5** (AMT-500) — validation, straightforward Pydantic change
4. **P0 item 3** (RACE-DEP) — concurrency fix, most complex
5. **P1 item 6** (RL-BURST) — rate limiting redesign, most complex
6. **P2 ops items** — manual server tasks

## Verification

After all code fixes, re-run external audit against sandbox to confirm findings are resolved.
