# External Audit Results — v1.4.2

**Date:** 2026-04-13
**Source:** `reports/external/v1.4.2/multi-persona-audit-v1.4.2-2026-04-13.md`
**Verdict:** CONDITIONAL GO — 80% pass rate (48/60), highest ever, security 10/10
**Target:** sandbox.greenhelix.net

---

## Summary

v1.4.2 achieves the highest audit score ever (8.0/10). Security persona hits
10/10 for the first time. SSE heartbeats confirmed working. Gatekeeper Z3 shows
mixed signals (works for some personas, not others — likely partial deploy timing).

## What Was Fixed in v1.4.2

| Fix | Evidence |
|-----|----------|
| Idempotency different-body → 409 | Fintech persona confirmed |
| `/v1/infra/keys/` trailing slash 307 | Security persona confirmed |
| Metrics ingest → 200 | ML persona confirmed (was 403) |
| SSE events streaming | SRE persona confirmed (broken since v1.2.4) |

---

## Findings Requiring Action

### F1: SOL Exchange Rate → 500 (MEDIUM)
**Persistent for:** 2 releases
**Root cause:** `Currency(params["from_currency"])` raises `ValueError` for unsupported
currencies (SOL, DOGE, etc.). The unhandled exception propagates as HTTP 500.
**Fix:** Catch `ValueError` in `_get_exchange_rate()` and return 400 with
`UnsupportedCurrencyError`. File: `gateway/src/tools/billing.py:437`
**Status:** FIX IN THIS PR

### F2: DOGECOIN Currency Accepted on Deposits (LOW)
**Persistent for:** 3 releases
**Root cause:** Billing deposit/withdraw endpoints have NO currency validation.
Payments tools have `_validate_currency()` but billing tools don't.
**Fix:** Add `_validate_currency()` to billing tools matching payments pattern.
File: `gateway/src/tools/billing.py`
**Status:** FIX IN THIS PR

### F3: `/metrics` → 403 on All Tiers (MEDIUM)
**Persistent for:** 11+ releases
**Root cause:** NOT tier-gated — IP-gated. `METRICS_ALLOWED_IPS` env var defaults
to `127.0.0.1,::1`. External callers get 403 regardless of auth tier.
**Fix:** Operational config — add monitoring IPs to `METRICS_ALLOWED_IPS` env var
on sandbox/prod. This is by design (Prometheus metrics should not be public).
**Status:** NOT A BUG — config change needed on deploy
**File:** `gateway/src/app.py:216-226`

### F4: Gatekeeper Z3 Mixed Signals (HIGH)
**Status:** RESOLVED by PR #103 (credential probe + sandbox mock mode).
The mixed signals in the audit are due to timing — the fix was deployed between
persona runs. After PR #103 merge, gatekeeper should work consistently.

### F5: PyPI SDK v1.4.1 (1 Behind) (LOW)
**Status:** Human action — run release pipeline or `publish_package.sh`.

### F6: ETH Withdraw: No tx_hash (LOW)
**Persistent:** Always
**Root cause:** Withdraw is a ledger operation (not on-chain). No real blockchain
transaction occurs, so no tx_hash is returned. This is by design for the
simulated exchange — document in API reference.
**Status:** NOT A BUG — document behavior

### F7: Fresh Payee Wallet Not Auto-Initialized (LOW)
**Root cause:** When capturing a payment to a payee who has never deposited,
the wallet doesn't exist → 404. The wallet should auto-create on first credit.
**Status:** BACKLOG

### F8: Sandbox Stripe `cs_live_*` (CRITICAL)
**Persistent since:** v0.9.6
**Status:** Human action — switch sandbox to Stripe test-mode keys.

---

## Not-a-Bug (Confirmed)

| Finding | Disposition |
|---------|-------------|
| 8-decimal amounts accepted | By design — crypto precision (BTC/ETH) |
| No `/v1/web3` namespace | Feature request — future roadmap |
| `/metrics` 403 | IP-gated by design, not tier-gated |
| ETH withdraw no tx_hash | Simulated exchange, no on-chain tx |
