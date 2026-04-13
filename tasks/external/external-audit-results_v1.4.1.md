# External Audit Results — v1.4.1

**Date:** 2026-04-13
**Source:** `reports/external/v1.4.1/multi-persona-audit-v1.4.1-2026-04-13.md`
**Personas:** 6 (Fintech, Security, ML/AI, Web3, SRE, Indie+SDK)
**Overall:** 48/60 pass (80%) — CONDITIONAL GO

---

## Score Summary

| Persona | Pass/Total | Score |
|---------|-----------|-------|
| Fintech | 8/10 | 80% |
| Security | 9/10 | 90% |
| ML/AI | 5/8 | 63% |
| Web3 | 5/10 | 50% |
| SRE | 9/10 | 90% |
| Indie+SDK | 12/12 | **100%** |

---

## Findings Requiring Action

### HIGH — Gatekeeper Z3 (10th consecutive release)

**Status:** FIX IN PROGRESS (PR #102, branch `fix/z3-boto3-probe`)

**Root cause (confirmed):** Sandbox postinst sets `VERIFIER_AUTH_MODE=iam` and
installs `boto3` but NOT `z3-solver`. The gateway creates a `VerifierClient`
(Lambda-based), but there are no AWS credentials on the sandbox host. Every
`invoke()` call fails, and `GatekeeperAPI._execute_job()` catches the exception
and marks the job as `status=failed, result=error`.

**Fix applied:**
1. `gateway/src/lifespan.py` — Added eager credential probe: after `VerifierClient`
   init, check `boto3.Session().get_credentials()`. If None, raise → falls back to
   `MockVerifierClient` (in-process Z3).
2. `package/a2a-gateway-sandbox/DEBIAN/postinst` — Changed to `VERIFIER_AUTH_MODE=mock`,
   replaced `boto3` with `z3-solver` in pip install.
3. Tests: `TestAuditZ3Regression` reproduces exact auditor payloads (SAT, UNSAT, spec).
   `test_iam_mode_without_credentials_falls_back` verifies the credential probe.

### MEDIUM — `/metrics` → 403 on all tiers

**Status:** PENDING
Endpoint deployed (was 404 for 9 releases, now 403). Needs tier-gating opened
for pro/enterprise tiers. See `tasks/backlog/v1.4.0-audit-remediation.md`.

### MEDIUM — SSE heartbeats broken (since v1.2.4)

**Status:** PENDING
Data events stream but no heartbeat/ping frames. Needs investigation of
asyncio keepalive in SSE route handler.

### MEDIUM — SOL exchange rate → 500

**Status:** NEW
Unsupported currency `SOL` crashes the server (500 Internal Server Error).
Should return 422 with currency not supported message.

### LOW — 8-decimal amounts accepted (1.234567)

**Status:** PERSISTENT (2 releases)
Financial amounts should reject >2dp. Regex/validation not tightened.

### LOW — `/v1/infra/keys/` trailing slash → 307

**Status:** PERSISTENT (2 releases)
FastAPI redirect. Could add `redirect_slashes=False` on router.

### LOW — DOGECOIN accepted on deposit

**Status:** PERSISTENT (2 releases)
Currency validation gap. Need allowlist check.

### LOW — Idempotency different-body returns 200 (not 409)

**Status:** PERSISTENT (2 releases)
Same idempotency key with different body should return 409 Conflict.

### LOW — ETH withdraw: no tx_hash in response

**Status:** BY DESIGN (persistent)

### LOW — No /v1/web3 or /v1/crypto namespace

**Status:** BY DESIGN (persistent)

---

## Positive Highlights

- **SDK achieves first-ever perfect 12/12 score** — both PyPI and npm at v1.4.1
- All v1.4.0 fixes confirmed holding (wallet capture, refund, idempotency, concurrency, XSS, SQL injection, BOLA, healthz)
- Overall platform score stable at 7.7/10
