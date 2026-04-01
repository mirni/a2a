# Fix SDK Compatibility with Phase 3 REST Routes

**Priority:** BLOCKER (B1 + B2)
**Source:** Market Readiness Audit 2026-04-01
**Effort:** 3-5 days

## Problem

Phase 3 API refactoring migrated tools from `/v1/execute` to dedicated REST routes (e.g., `/v1/billing/wallets/{agent_id}/balance`). Both SDKs still call `/v1/execute` for these tools and receive 410 Gone.

## Scope

### Python SDK (`sdk/`)
- Update all convenience methods to call REST endpoints instead of `/v1/execute`
- Fix 8 failing tests in `sdk/tests/`
- Update SDK version

### TypeScript SDK (`sdk-ts/`)
- Same REST endpoint migration
- Publish to npm (currently v0.1.0, not published)
- Add README with quickstart

### E2E Tests (`e2e_tests.py`)
- Update 21 failing tests to use REST endpoints
- Validate all 47 tests pass

## Acceptance Criteria
- [ ] `python -m pytest sdk/tests/ -x -q` — 0 failures
- [ ] `python -m pytest e2e_tests.py -x -q` — 0 failures
- [ ] TypeScript SDK published on npm
- [ ] Both SDKs have README.md with installation and quickstart
