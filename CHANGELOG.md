# Changelog

# Release v0.4.2

**Date:** 2026-03-31
**Commit:** aa207e5a
**Previous:** v0.3

## Changes

### Features

- feat: extract deployment logic into scripts/deploy.sh CLI (`aa207e5`)
- feat: 21-item customer report fixes (security, auth, pagination, data quality, API) (#2) (`f09577a`)

### Bug Fixes

- feat: extract deployment logic into scripts/deploy.sh CLI (`aa207e5`)
- fix: resolve CI failures — lint, typecheck, semgrep, test (#1) (`fe2dbb7`)

### Documentation

- docs: add INFRA.md — complete CI/CD pipeline reference for reuse (`da2cb4f`)

## Components

| Package | Version |
|---------|---------|
| a2a-gateway | 0.4.2 |
| a2a-gateway-test | 0.4.2 |
| a2a-website | 0.4.2 |
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
