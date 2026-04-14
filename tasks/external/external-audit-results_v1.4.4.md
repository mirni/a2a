# External Audit Results — v1.4.4

**Date:** 2026-04-14
**Source:** `reports/external/v1.4.4/multi-persona-audit-v1.4.4-2026-04-14.md`
**Target:** sandbox.greenhelix.net
**Tests:** 60 total, 48 pass, 12 fail (80%)
**Score:** 7.7/10 (down from 8.0 in v1.4.2)

---

## Confirmed Fixes (v1.4.2 → v1.4.4)

| Fix | Evidence |
|-----|----------|
| DOGECOIN deposit rejected | 400 with currency whitelist (was 200) |
| SOL exchange rate | 400 validation error (was 500 crash) |
| Fresh payee wallet auto-init | Capture between fresh agents works (was 404) |

---

## Findings

### F1 — Idempotency different-body returns 201 (REGRESSED) — MEDIUM

**Root cause identified:** The route-level idempotency gate
(`gateway/src/deps/idempotency.py:113`) reads the key from the
`Idempotency-Key` HTTP header only. The audit sends `idempotency_key`
in the JSON body field. The body field is forwarded to the tool, which
does its own check — but only returns the cached result without 409
on body mismatch.

**Fix:** In `check_idempotency()`, also fall back to the body field:
```python
idem_key = request.headers.get("idempotency-key")
if not idem_key:
    # Also check body field (backward compat with /v1/execute callers)
    idem_key = body.get("idempotency_key") if isinstance(body, dict) else None
if not idem_key:
    return None
```

**File:** `gateway/src/deps/idempotency.py` line 113
**Status:** ACTIONABLE

### F2 — Gatekeeper Z3 100% failure — HIGH

12th consecutive release. Jobs submit (201) but immediately fail with
`status=failed, result=error`. The Lambda verifier is broken; the
in-process Z3 mock should work but sandbox apparently isn't using it.

**File:** Deployment/ops issue (boto3/z3-solver on sandbox)
**Status:** OPS — deploy v1.4.4 deb with z3-solver to sandbox

### F3 — `/metrics` → 403 — MEDIUM

IP-gated by design (`METRICS_ALLOWED_IPS` defaults to `127.0.0.1,::1`).
External clients always get 403. The audit also reports 404, likely from
hitting `/metrics` instead of `/v1/metrics`.

**File:** `gateway/src/app.py` line 216
**Status:** BY DESIGN — not a bug; could add tier-gated access as enhancement

### F4 — SDK versions 2 behind (1.4.2 vs 1.4.4) — MEDIUM

Both PyPI and npm SDKs are at v1.4.2 while server is v1.4.4.

**Status:** OPS — republish SDKs

### F5 — Decimal precision >2dp accepted on deposits — LOW

`1.234567` accepted on deposit (6 decimal places). Financial amounts
should be capped at 2 decimal places.

**Status:** ENHANCEMENT — add max 2dp validation to deposit/withdraw

### F6 — ETH withdraw: no tx_hash — LOW

ETH withdrawals succeed but return no `tx_hash` in response. Expected
for a non-blockchain platform — ETH is just a currency denomination.

**Status:** BY DESIGN

### F7 — No /v1/web3 namespace — LOW

No dedicated web3/crypto endpoints. Crypto operations use existing
currency conversion and billing endpoints.

**Status:** BY DESIGN

### F8 — Performance-gated escrow endpoint 404 — LOW

`/v1/payments/performance-escrows` returns 404. This endpoint doesn't
exist; performance escrows use the standard escrow flow with SLA
conditions.

**Status:** BY DESIGN — document in API reference

---

## What Works Well

- Security: 10/10 for 2nd consecutive release (BOLA, auth, XSS, SQLi, path traversal)
- Currency validation tightened (DOGECOIN, SOL properly rejected)
- RFC 9457 error format properly implemented
- Rate limiting headers present and correct
- SSE streaming functional
- DB integrity checks pass
- SDK smoke test works (register → deposit → intent → capture)

---

## Remediation Priority

| # | Finding | Severity | Action |
|---|---------|----------|--------|
| 1 | F1: Idempotency body-field key | MEDIUM | Code fix in idempotency.py |
| 2 | F2: Gatekeeper Z3 | HIGH | Deploy with z3-solver to sandbox |
| 3 | F4: SDK versions | MEDIUM | Republish PyPI + npm |
| 4 | F5: Decimal precision | LOW | Add 2dp validation |
| 5 | F3/F6/F7/F8 | LOW | By design / documentation |
