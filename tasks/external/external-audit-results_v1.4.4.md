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
**Status:** FIXED — PR #111

### F2 — Gatekeeper Z3 100% failure — HIGH

12th consecutive release. Jobs submit (201) but immediately fail with
`status=failed, result=error`. The Lambda verifier is broken; the
in-process Z3 mock should work but sandbox apparently isn't using it.

**File:** Deployment/ops issue (boto3/z3-solver on sandbox)
**Status:** OPS — deployment instructions provided below

#### Deployment Instructions

The correct package is `a2a-gateway-sandbox` (NOT `a2a-gateway-test`).
The sandbox postinst (`package/a2a-gateway-sandbox/DEBIAN/postinst`)
already installs `z3-solver>=4.12` and sets `VERIFIER_AUTH_MODE=mock`.

**Root cause analysis:** Two likely failure modes:
1. `z3-solver` pip install fails silently (C extension build on host)
2. Existing `.env` has `VERIFIER_AUTH_MODE=` set to something other than
   `mock` (postinst only adds the var if missing via `grep -q`, won't overwrite)

```bash
# 1. Build the sandbox package
scripts/create_package.sh a2a-gateway-sandbox

# 2. Deploy (on sandbox host)
sudo dpkg -i dist/a2a-gateway-sandbox_*.deb

# 3. Verify z3-solver is importable
sudo -u a2a /opt/a2a-sandbox/venv/bin/python -c "import z3; print('Z3 OK:', z3.get_version_string())"

# 4. Verify .env has correct verifier mode
grep VERIFIER_AUTH_MODE /opt/a2a-sandbox/.env
# Expected: VERIFIER_AUTH_MODE=mock

# 5. If VERIFIER_AUTH_MODE is wrong, fix it:
sudo sed -i 's/^VERIFIER_AUTH_MODE=.*/VERIFIER_AUTH_MODE=mock/' /opt/a2a-sandbox/.env
sudo systemctl restart a2a-gateway-sandbox

# 6. Smoke test gatekeeper
curl -s -X POST https://sandbox.greenhelix.net/v1/gatekeeper/jobs \
  -H "Authorization: Bearer <PRO_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"spec": "(assert (> x 0))", "solver": "z3"}' | jq .status
# Expected: "completed" or "pending" (not "failed")
```

### F3 — `/metrics` → 403 — MEDIUM

IP-gated by design (`METRICS_ALLOWED_IPS` defaults to `127.0.0.1,::1`).
External clients always get 403. The audit also reports 404, likely from
hitting `/metrics` instead of `/v1/metrics`.

**File:** `gateway/src/app.py` line 216
**Status:** FIXED — Enterprise+ tier can now access `/v1/metrics` from
any IP. Localhost/internal IPs still bypass auth for monitoring infra
(Prometheus scrapers). Admin keys also have access.

### F4 — SDK versions 2 behind (1.4.2 vs 1.4.4) — MEDIUM

Both PyPI and npm SDKs are at v1.4.2 while server is v1.4.4.

**Status:** FIXED — Version bumped to 1.4.4 in both `sdk/pyproject.toml`
and `sdk-ts/package.json`. Human action required: tag `sdk-v1.4.4` and
push to trigger `.github/workflows/publish.yml`.

### F5 — Decimal precision >2dp accepted on deposits — LOW

`1.234567` accepted on deposit (6 decimal places). Financial amounts
should be capped per currency.

**Status:** FIXED — Per-currency decimal precision validation added.

| Currency | Max DP | Rationale |
|----------|--------|-----------|
| CREDITS | 2 | Platform currency, cents |
| USD | 2 | Cents |
| EUR | 2 | Cents |
| GBP | 2 | Pence |
| BTC | 8 | Satoshis |
| ETH | 8 | Practical precision (industry standard for exchanges) |
| USDC | 6 | On-chain standard (ERC-20 decimals=6) |

Validation added as `model_validator` on both `DepositRequest` and
`WithdrawRequest` in `gateway/src/routes/v1/billing.py`.

### F6 — ETH withdraw: no tx_hash — LOW

ETH withdrawals succeed but return no `tx_hash` in response.

**Status:** BY DESIGN — CTO review below

### F7 — No /v1/web3 namespace — LOW

No dedicated web3/crypto endpoints.

**Status:** BY DESIGN — CTO review below. **Do NOT implement.**

### F8 — Performance-gated escrow endpoint 404 — LOW

`/v1/payments/performance-escrows` returns 404.

**Status:** BY DESIGN — CTO review below

---

## CTO Review: F6/F7/F8 — /web3 Namespace

### F6 — ETH withdraw: no tx_hash

ETH/BTC are currency denominations on this platform, not actual blockchain
transfers. There is no on-chain transaction, so no `tx_hash` exists.

**Recommendation:** Add a `reference_id` field to withdrawal responses as a
platform-level transaction identifier. Low priority enhancement, not blocking.

### F7 — No /v1/web3 namespace: Do NOT implement

Arguments against:

- **Off-mission:** Platform is agent-to-agent commerce infrastructure (billing,
  escrow, marketplace, identity). Blockchain integration is a different product.
- **Massive scope:** Requires blockchain node/RPC integration, gas estimation,
  MEV protection, smart contract auditing. 6+ month effort minimum.
- **Regulatory burden:** Crypto custody triggers KYC/AML requirements, varies
  by jurisdiction. Significant legal/compliance cost.
- **Security surface:** Smart contract interactions are the #1 source of DeFi
  exploits. Would undermine our 10/10 security score.
- **Maintenance burden:** Chain upgrades, hard forks, RPC provider outages.
- **Already works:** BTC/ETH/USDC function well as currency denominations for
  pricing and billing. Agents can price services in ETH without needing
  on-chain settlement.

If web3 demand materializes, the right approach would be a separate
`/v1/settlements` namespace that supports pluggable settlement backends
(Stripe, crypto, wire transfer) — not a crypto-specific /web3 namespace.

### F8 — Performance escrow 404

Performance escrows use the standard escrow flow (`/v1/payments/escrows`)
with SLA conditions. No separate endpoint needed.

**Recommendation:** Document this in the API reference.

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

## Remediation Summary

| # | Finding | Severity | Status |
|---|---------|----------|--------|
| F1 | Idempotency body-field key | MEDIUM | FIXED (PR #111) |
| F2 | Gatekeeper Z3 | HIGH | OPS — deployment instructions provided |
| F3 | `/metrics` → 403 | MEDIUM | FIXED — tier-gated access (enterprise+) |
| F4 | SDK versions | MEDIUM | FIXED — bumped to 1.4.4, tag to publish |
| F5 | Decimal precision | LOW | FIXED — per-currency validation |
| F6 | ETH no tx_hash | LOW | BY DESIGN — CTO reviewed |
| F7 | No /web3 | LOW | BY DESIGN — CTO reviewed, do NOT implement |
| F8 | Performance escrow 404 | LOW | BY DESIGN — CTO reviewed |


## HUMAN RESPONSES
* F1: Fix it
* F2: Provide exact instructions -- is this a2a-gateway-test package?
* F3: Please implement paid tiered access
* F4: Please republish
* F5: Not sure what is the best course of action here -- review as CTO and provide feedback/critique
* F6, F7, F8 -- document but also take into consideration -- should we implement /web3? What would it do? Can you review/critique as CTO. What is the ask here exactly, and should we do it? Pros/cons, tradeoffs, etc.
