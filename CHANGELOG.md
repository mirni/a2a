# Changelog

# Release v0.8.1

**Date:** 2026-04-02
**Commit:** 744b802b
**Previous:** v0.7.0

## Changes

### Features

- feat: audit remediation — security headers, nginx hardening, idempotency (#31) (`8c5d783`)

### Bug Fixes

- fix: resolve SAST and test failures on release pipeline (#32) (`744b802`)
- fix: audit remediation — security, SDK REST migration, backup package (#28) (`9379c7b`)

### Tests

- test: improve gateway test coverage (#29) (`91a1cb3`)

### Other

- task: review external security audit findings (#30) (`8fb6952`)
- Squashed commit of the following: (`2e10b05`)
- Update master log post-merge (`2f30b3a`)
- audit: external + internal market-readiness audit (#27) (`41b1888`)
- Merge release v0.7.0 into main (`90a57a2`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.8.1 |
| a2a-db-backup | 0.8.1 |
| a2a-gateway | 0.8.1 |
| a2a-gateway-sandbox | 0.8.1 |
| a2a-gateway-test | 0.8.1 |
| a2a-website | 0.8.1 |
---


# Release v0.7.0

**Date:** 2026-04-01
**Commit:** a33d3b19
**Previous:** v0.6.0

## Changes

### Bug Fixes

- fix: security audit remediation (24 findings) (#26) (`62154d6`)

### Refactoring

- refactor: restrict /v1/execute to connector tools only (#25) (`2fe321d`)
- refactor: API Phase 3 — remaining resource endpoints (marketplace, trust, messaging, infra, disputes) (#23) (`9ca566f`)
- refactor: API Phase 2 — resource endpoints (billing, payments, identity) (#22) (`b1b82cd`)
- refactor: API Foundation Phase 1 (T3–T9) (#21) (`e47d590`)

### Other

- Update MASTER_LOG.md with latest (`a33d3b1`)
- report: internal security audit of A2A gateway REST API (#24) (`79db577`)
- Fix the release pipeline -- CD must wait for CI to finish; Add missed 'done' prompt (`9c41086`)
- Merge release v0.6.0 into main (`bdc5151`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.7.0 |
| a2a-gateway | 0.7.0 |
| a2a-gateway-sandbox | 0.7.0 |
| a2a-gateway-test | 0.7.0 |
| a2a-website | 0.7.0 |
---


# Release v0.6.0

**Date:** 2026-03-31
**Commit:** 1acdc903
**Previous:** v0.5.3

## Changes

### Refactoring

- refactor: optimize CI/CD pipeline — lightweight PRs, thorough releases (#20) (`1acdc90`)
- refactor: migrate gateway from Starlette to FastAPI (#19) (`cd06118`)
- refactor: organize .md files into structured directories (`de4f286`)

### Documentation

- docs: API design review — Richardson Maturity Model assessment (`a0e8dd7`)

### Other

- Add _EXAMPLE.md for humand and _INSTRUTIONS_FO_CLAUDE.md for claude on how to treat the tasks/ files (`0d459a0`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.6.0 |
| a2a-gateway | 0.6.0 |
| a2a-gateway-sandbox | 0.6.0 |
| a2a-gateway-test | 0.6.0 |
| a2a-website | 0.6.0 |
---


# Release v0.4.9

**Date:** 2026-03-31
**Commit:** 74e8b08e
**Previous:** v0.3

## Changes

### Features

- feat: extract deployment logic into scripts/deploy.sh CLI (`aa207e5`)
- feat: 21-item customer report fixes (security, auth, pagination, data quality, API) (#2) (`f09577a`)

### Bug Fixes

- fix: extract a2a-common package to resolve dpkg file conflicts (`74e8b08`)
- fix: add dpkg lock retry to deploy.sh (120s timeout) (`50e4e7f`)
- fix: make deb postinst scripts self-contained (#5) (`6c3a340`)
- feat: extract deployment logic into scripts/deploy.sh CLI (`aa207e5`)
- fix: resolve CI failures — lint, typecheck, semgrep, test (#1) (`fe2dbb7`)

### Documentation

- docs: CMO distribution plan with 40 prioritized action items (#4) (`0d46277`)
- docs: add INFRA.md — complete CI/CD pipeline reference for reuse (`da2cb4f`)

### Tests

- docs: CMO distribution plan with 40 prioritized action items (#4) (`0d46277`)

### Other

- release: v0.4.8 (`987cad4`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.4.9 |
| a2a-gateway | 0.4.9 |
| a2a-gateway-sandbox | 0.4.9 |
| a2a-gateway-test | 0.4.9 |
| a2a-website | 0.4.9 |
---


# Release v0.4.8

**Date:** 2026-03-31
**Commit:** 50e4e7ff
**Previous:** v0.3

## Changes

### Features

- feat: extract deployment logic into scripts/deploy.sh CLI (`aa207e5`)
- feat: 21-item customer report fixes (security, auth, pagination, data quality, API) (#2) (`f09577a`)

### Bug Fixes

- fix: add dpkg lock retry to deploy.sh (120s timeout) (`50e4e7f`)
- fix: make deb postinst scripts self-contained (#5) (`6c3a340`)
- feat: extract deployment logic into scripts/deploy.sh CLI (`aa207e5`)
- fix: resolve CI failures — lint, typecheck, semgrep, test (#1) (`fe2dbb7`)

### Documentation

- docs: CMO distribution plan with 40 prioritized action items (#4) (`0d46277`)
- docs: add INFRA.md — complete CI/CD pipeline reference for reuse (`da2cb4f`)

### Tests

- docs: CMO distribution plan with 40 prioritized action items (#4) (`0d46277`)

## Components

| Package | Version |
|---------|---------|
| a2a-gateway | 0.4.8 |
| a2a-gateway-sandbox | 0.4.8 |
| a2a-gateway-test | 0.4.8 |
| a2a-website | 0.4.8 |
---


All notable changes to the A2A Commerce Platform are documented in this file.

## [0.2.0] — 2026-03-28

### Features
- **23 customer feedback items (P0–P3):** Stripe checkout, MCP proxy, TypeScript SDK parity, rate limiting improvements, webhook hardening, and more — all implemented with TDD (9378ce2)
- **SQLite database security:** automated backup/restore, file hardening, integrity checks (a1458dd)
- **Tailscale SSH access:** remote server access for traveling users via deploy.sh (76c787d)
- **Company website:** greenhelix.net static site with deployment support (30ab0ee)
- **Deployment refactor:** modular deploy scripts (`deploy_a2a.sh`, `deploy_website.sh`, `common.bash`) + Debian `.deb` package build (d413364)
- **Server shell config:** smoke tests, QA audit improvements (15324b1)
- **Health check script:** `check_server.sh` for quick server verification (4ce1de7)

### Infrastructure
- **CI script extraction:** inline bash/Python in GitHub Actions replaced with 6 standalone scripts under `scripts/ci/` — install_deps, docker_build_verify, start/stop_gateway, provision_admin_key, post_summary (cb689cc)
- **Nightly stress test workflow:** automated load testing with configurable concurrency, duration, and target URL (cb689cc)
- **`run_tests.sh`:** deduplicated pytest invocations across CI with per-module PYTHONPATH isolation (3f1e920)
- **CLAUDE.md:** TDD workflow enforced via project instructions (c08bb68)

### Bug Fixes
- Cloud-init compatibility for Hetzner deployments (fc45a09)
- Private repo clone via `GITHUB_PAT` in deploy.sh (b606d72)
- Skip apt operations in deb postinst when dpkg holds the lock (080cb86)
- Default domains set to api.greenhelix.net / greenhelix.net (f4b6d42)

### Tests
- 291 gateway tests passing (up from ~200 in v0.1)
- New test suites for Stripe checkout, MCP proxy, TypeScript SDK (81097f2)

## [0.1.0] — 2026-03-27

Initial release. Docker deployment, GitHub Actions CI, core gateway with billing, paywall, payments, marketplace, trust, identity, and SDK modules.
