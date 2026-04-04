# Market-Readiness Audit — v0.9.1

## Role
You are a pragmatic engineering lead conducting a pre-launch market-readiness audit. Your job is to verify what works, flag what's broken, and produce a prioritized punch list — not a wishlist.

## Context

**Product:** Green Helix — A2A Commerce Gateway (128 tools, 148 endpoints)
**Version:** v0.9.1 (2026-04-02)
**Prior audits:**
- Internal audit (2026-04-01): 32 findings, graded B+ security / A financial / D+ DX
- External security audit v0.8.4: 12 findings, all P0/P1 code fixes verified
- Pre-launch audit (2026-04-02): CONDITIONAL GO, 3 new P0 items identified

**Known open issues from prior audits:**
- `/v1/register` returns 500 (onboarding broken)
- SDK breakage: Python + TS SDKs return 410 Gone after Phase 3 API migration
- E2E test regression: 21/47 failures from same migration
- Missing idempotency on capture/release/cancel
- Stripe webhook dedup uses in-memory set (lost on restart)
- `/.well-known/agent-card.json` not implemented
- No automated DB backup
- `/metrics` endpoint is public (no auth)
- No runbooks or incident response plan

## Goal

Verify the current state of the codebase against launch requirements. Produce a single actionable punch list that separates blockers from nice-to-haves.

## Tasks

### 1. Blocker Verification
Test each known blocker against the **current codebase** (not prior audit reports — code may have changed):
- [ ] `/v1/register` — does it still 500? Trace the error.
- [ ] SDK clients — do they still hit 410? Check if SDK was updated for Phase 3 routes.
- [ ] E2E tests — run `python e2e_tests.py` and report pass/fail count.
- [ ] `/.well-known/agent-card.json` — is there a route for it?
- [ ] DB backup script — does `scripts/backup_db.sh` exist? Is it cron-ready?

### 2. Security Punch List
- [ ] Verify `max amount` validation exists on deposit/withdraw (`Field(gt=0, le=...)`)
- [ ] Verify BOLA error messages are sanitized (no input reflection in 403s)
- [ ] Verify webhook error handling catches broad exceptions (not just `httpx.HTTPError`)
- [ ] Check `/metrics` — is it auth-gated?
- [ ] Check idempotency coverage — which mutation endpoints lack `idempotency_key`?

### 3. Distribution Readiness
- [ ] Can `a2a-sdk` be published to PyPI? Check `pyproject.toml` for: README, author, license, classifiers, homepage.
- [ ] Can `@greenhelix/sdk` be published to npm? Check `package.json` for: README, author, repository, publishConfig, license.
- [ ] Does `AGENTS.md` exist in repo root?
- [ ] Does `SKILL.md` exist in repo root?
- [ ] Review `docs/infra/DISTRIBUTION.md` — are action items current?

### 4. Test Health
- [ ] Run full gateway test suite: `HOME=/tmp python -m pytest gateway/tests/ -x -q`
- [ ] Run full product test suites: `HOME=/tmp python -m pytest products/*/tests/ -x -q`
- [ ] Report coverage if available. Target: 94%+.
- [ ] Flag any tests that are skipped, xfail, or flaky.

### 5. Operational Readiness
- [ ] Does `scripts/backup_db.sh` exist and is it functional?
- [ ] Are Prometheus alerts defined? Check `monitoring/prometheus/alerts.yml` for: DB failures, webhook failures, auth spikes, backup failures.
- [ ] Is there a rollback procedure documented anywhere?
- [ ] Check deployment scripts work: `scripts/create_package.sh ALL`

### 6. DX Smoke Test
Simulate a new developer onboarding:
- [ ] Clone, install deps, run tests — does it work in <5 min?
- [ ] Is there a minimal "Hello World" example in `examples/`?
- [ ] Can a developer get an API key and make a successful API call from the README alone?

## Output

Produce a single report with:

1. **Verdict:** GO / CONDITIONAL GO / NO-GO with rationale
2. **Blockers table:** Items that must be fixed before launch (with file paths and fix descriptions)
3. **Sprint table:** Items for first 2 weeks post-launch
4. **Backlog table:** Everything else
5. **Scores:** Security, Financial, QA, DX, Ops — each graded A-F with brief justification
6. **Delta from last audit:** What improved, what regressed, what's unchanged

Save report to `reports/market-readiness-audit-v0.9.1.md`.

## Rules
- Test against the actual codebase, not assumptions from prior reports
- Run real commands — don't guess at test results
- If something was "fixed" in a prior audit, verify it's still fixed
- Be honest about NO-GO items — don't paper over launch blockers
- Keep the report under 500 lines

## Completed
- **Date:** 2026-04-03
- **Report:** `reports/market-readiness-audit-v0.9.1.md`
- **Summary:** CONDITIONAL GO (B / 83). 3 blockers (payment amount validation, BOLA info-disclosure, register live verification), 5 sprint items, 5 backlog. Major improvements since v0.7.0: SDK 410 fixed, agent-card added, backup script exists, +52% test count, overall grade C+ → B.
