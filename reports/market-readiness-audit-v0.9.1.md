# Market-Readiness Audit Report — v0.9.1

**Date:** 2026-04-03
**Version:** 0.9.1
**Auditor:** Claude (automated static + dynamic audit)
**Prior audits:** v0.7.0 internal (2026-04-01), v0.8.4 external security, v0.9.0 pre-launch (2026-04-02)

---

## 1. Verdict: CONDITIONAL GO

The platform has made significant progress since the v0.7.0 audit (C+ / 74.5). Most prior blockers are resolved. Two blockers remain, plus one new finding.

**Weighted Score: 83 / 100 (B)**

| Area | Grade | Score | Notes |
|------|-------|-------|-------|
| Security | B+ | 85 | Webhook handling solid; BOLA info-disclosure in payments.py; payment amount validation gaps |
| Financial | A- | 92 | Billing validated; payment amounts lack upper-bound constraints |
| QA / Test | A- | 91 | ~1,610 tests, all green in CI; 9 modules above baseline; no skips/xfails |
| DX | B- | 75 | SDKs aligned; AGENTS.md + SKILL.md exist; API key onboarding unclear in README |
| Ops | B | 82 | Backup script exists + cron-ready; rollback automated; missing domain-specific Prometheus alerts |
| **Weighted Total** | **B** | **83** | |

---

## 2. Blockers (must fix before launch)

| # | Item | Severity | File(s) | Fix |
|---|------|----------|---------|-----|
| B1 | Payment amount models lack `Field(gt=0, le=...)` | P0 | `gateway/src/routes/v1/payments.py` lines 61, 82, 105, 113, 135, 164 | Add `Field(gt=0, le=1_000_000_000, decimal_places=2)` to all `amount: Decimal` fields (billing routes already have this) |
| B2 | BOLA info-disclosure: 403 responses leak payer/payee identities | P0 | `gateway/src/tools/payments.py` lines 21-22, 35-36, 49-50 | Sanitize error messages — return generic "Forbidden: you do not have access to this resource" instead of revealing intent/escrow parties |
| B3 | `/v1/register` — needs live verification | P1 | `gateway/src/routes/register.py` | Code is correct but 500 depends on runtime storage backend state. Must verify with live call to sandbox before launch. |

---

## 3. Sprint Table (first 2 weeks post-launch)

| # | Item | Priority | File(s) | Notes |
|---|------|----------|---------|-------|
| S1 | Missing idempotency on capture, release, cancel, refund, reactivate, split | P1 | `gateway/src/tools/payments.py`, `catalog.json` | 12 financial mutation endpoints lack idempotency enforcement. Only deposit/withdraw/create_* have it. |
| S2 | Add Prometheus alerts for DB failures, webhook failures, auth spikes, backup failures | P1 | `monitoring/prometheus/alerts.yml` | Current alerts only cover infra (CPU, memory, disk, gateway down). No application-level alerts. |
| S3 | API key onboarding in README | P2 | `README.md` | README says "see `products/paywall/`" — needs a curl command or self-service instructions |
| S4 | Update DISTRIBUTION.md stale action items | P2 | `docs/infra/DISTRIBUTION.md` | AGENTS.md, SKILL.md marked pending but exist; `@a2a/sdk` ref should be `@greenhelix/sdk` |
| S5 | Off-site backup replication | P2 | `scripts/backup_databases.sh` | Currently backs up to same host only. Single point of failure. |

---

## 4. Backlog

| # | Item | Notes |
|---|------|-------|
| L1 | Add `Framework :: AI` trove classifier to SDK `pyproject.toml` | Nice-to-have for PyPI discoverability |
| L2 | Trivial "Hello World" 5-line example in `examples/` | Current examples are full workflows |
| L3 | `/metrics` uses IP allowlist only, no bearer token | Acceptable behind Cloudflare; add token auth if exposing externally |
| L4 | Stripe webhook dedup uses in-memory set | Lost on restart; low urgency if Stripe retry-idempotency suffices |
| L5 | E2E test suite needs live API key for execution | 44 tests, structurally aligned with current API, but can only run against live server |

---

## 5. Scores

### Security: B+ (85)
- Authorization: robust, no bypass across all 128 tools
- Webhook error handling: comprehensive (`except Exception`)
- `/metrics`: IP-allowlisted (localhost default), hidden from OpenAPI
- **Gap:** Payment BOLA info-disclosure (B2), missing amount validation on payment models (B1)
- **Gap:** Identity/infrastructure error messages also reflect user input, lower severity

### Financial: A- (92)
- Billing deposit/withdraw: properly constrained with `Field(gt=0, le=1_000_000_000, decimal_places=2)`
- All currency fields use `Decimal`, never `float`
- **Gap:** 8 payment route amount fields have bare `Decimal` with no constraints (B1)
- **Gap:** 12 mutation endpoints missing idempotency enforcement (S1)

### QA / Test: A- (91)
- ~1,610 tests across 9 modules, all passing in CI
- Coverage baseline: billing 84%, payments 88%, paywall 90%, gateway 94%, marketplace 94%, shared 95%, identity 96%, messaging 97%, trust 97%
- Average coverage: 92.8%
- Coverage ratchet enforced in CI (build fails on regression)
- No skipped or xfail tests detected
- **Gap:** E2E suite (44 tests) requires live server; cannot run in CI

### DX: B- (75)
- Both SDKs (Python + TS) fully aligned with v1 routes — 410 Gone issue **resolved**
- `AGENTS.md` (73 lines) and `SKILL.md` (94 lines) exist and are well-structured
- Both SDKs publish-ready: PyPI metadata complete, npm `publishConfig.access: "public"` set
- README has clear quickstart with curl examples
- 6 examples in `examples/` directory
- **Gap:** API key creation not documented for new developers (S3)
- **Gap:** DISTRIBUTION.md has stale action items (S4)

### Ops: B (82)
- `scripts/backup_databases.sh`: production-grade, uses `sqlite3 .backup`, integrity checks, 30-day retention, systemd timer package available
- `scripts/deploy.sh`: automated rollback via `dpkg-repack`, health checks, dry-run mode
- `scripts/create_package.sh`: builds 6 debs + SDK wheel
- Prometheus alerts: 6 infra alerts defined (error rate, latency, down, CPU, memory, disk)
- **Gap:** No application-level Prometheus alerts (S2)
- **Gap:** No off-site backup (S5)
- Rollback procedure: implemented AND documented in `docs/infra/INFRA.md`

---

## 6. Delta from Last Audit (v0.7.0 → v0.9.1)

| Item | v0.7.0 (Apr 1) | v0.9.1 (Apr 3) | Status |
|------|-----------------|-----------------|--------|
| SDK 410 Gone breakage | **BLOCKER** — both SDKs broken | **RESOLVED** — all paths aligned to `/v1/` | Fixed |
| E2E test regression (21/47 failures) | **BLOCKER** | **STRUCTURAL FIX** — all paths updated; needs live verification | Improved |
| `/.well-known/agent-card.json` | Missing | **RESOLVED** — handler in `gateway/src/routes/agent_card.py`, registered in app | Fixed |
| DB backup automation | None | **RESOLVED** — `backup_databases.sh` + systemd timer package | Fixed |
| `/v1/register` 500 error | **BLOCKER** | **CODE FIX** — handler correct, needs live verification | Improved |
| `/metrics` public endpoint | Unprotected | **MITIGATED** — IP allowlist (localhost default) + hidden from OpenAPI | Improved |
| Test count | 1,062 | ~1,610 | +52% |
| Gateway coverage | 93% | 94% | +1% |
| Overall grade | C+ (74.5) | B (83) | +8.5 pts |
| AGENTS.md | Missing | Present (73 lines) | Fixed |
| SKILL.md | Missing | Present (94 lines) | Fixed |
| Rollback procedure | Undocumented | Implemented + documented | Fixed |
| Runbooks | Missing | Partial (deploy.sh has auto-rollback; no incident response doc) | Improved |

**Regressions:** None detected.

**New findings:**
- B1: Payment amount validation (not audited before; newly identified)
- B2: BOLA info-disclosure in payment tools (not audited before; newly identified)
- S1: Idempotency gaps on financial mutations (known since prior audit; still open)
