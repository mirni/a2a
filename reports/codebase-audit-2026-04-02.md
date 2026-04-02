# Codebase Audit Report — 2026-04-02

**Scope:** Full repository dead code, orphaned files, unused functions, organizational issues.
**Method:** Automated analysis across 5 parallel audit passes (gateway, products, scripts/config, tests, markdown organization).

---

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Dead Code (gateway) | 1 | 1 | 2 | 1 | 5 |
| Dead Code (products) | 1 | 4 | 3 | 0 | 8 |
| Scripts & Config | 2 | 1 | 2 | 0 | 5 |
| Tests | 0 | 1 | 1 | 1 | 3 |
| Markdown Organization | 2 | 2 | 2 | 0 | 6 |
| **Total** | **6** | **9** | **10** | **2** | **27** |

**Estimated removable dead code:** ~2,500+ lines across gateway and products.

---

## 1. Gateway Dead Code

### 1.1 CRITICAL — Duplicate function: `calculate_tool_cost`

- **Files:** `gateway/src/deps/billing.py:11-31` AND `gateway/src/routes/execute.py:129-150`
- **Issue:** Identical function defined in two locations.
  - `execute.py` uses its own copy internally; `batch.py` imports from `execute.py`
  - `deps/tool_context.py` imports from `deps/billing.py`
- **Fix:** Keep in `deps/billing.py`, remove from `execute.py`, update `batch.py` import.

### 1.2 HIGH — Unused function: `check_balance`

- **File:** `gateway/src/deps/billing.py:34-42`
- **Issue:** Never called anywhere. Balance checking is done inline in `execute.py:446-455` and `deps/tool_context.py:113-130`.
- **Fix:** Delete function.

### 1.3 MEDIUM — Unused function: `get_tools_by_service`

- **File:** `gateway/src/catalog.py:37-39`
- **Issue:** Public function never called anywhere in the codebase.
- **Fix:** Delete unless planned for future public API.

### 1.4 MEDIUM — Similar rate limit header logic

- **Files:** `gateway/src/routes/execute.py:118-126` and `gateway/src/rate_limit_headers.py:94-119`
- **Issue:** Two implementations of `X-RateLimit-*` header construction with overlapping logic.
- **Fix:** Clarify separation (private/authenticated vs public/IP-based) or consolidate.

### 1.5 LOW — Import organization

- **Example:** `batch.py` imports `calculate_tool_cost` from `execute.py` instead of `deps/billing.py`
- **Fix:** Reorganize imports to follow `deps/` → `routes/` layering after fixing 1.1.

---

## 2. Products Dead Code

### 2.1 CRITICAL — Superseded module: `products/reputation/`

- **Path:** `/workdir/products/reputation/` (~1,500 lines)
- **Contents:** `aggregator.py`, `pipeline.py`, `probe_worker.py`, `scan_worker.py`, `storage.py`
- **Issue:** This is the **original standalone** reputation module. It was superseded when reputation was folded into the identity module (`products/identity/src/api.py:324-436`). Nobody imports from `products.reputation` — the gateway uses `identity_api.get_reputation()` instead. The reputation feature itself is alive (exposed via `GET /agents/{agent_id}/reputation` and the `get_agent_reputation` tool).
- **Fix:** Delete `products/reputation/` directory (the standalone version). The identity-integrated implementation remains.

### 2.2 HIGH — Unused module: `products/billing/src/org_billing.py`

- **Path:** `products/billing/src/org_billing.py` (~250 lines)
- **Issue:** `OrgBilling` class and 4 exception classes (`OrgInsufficientCreditsError`, `OrgSpendLimitExceededError`, `OrgWalletNotFoundError`, `NotOrgMemberError`) exported in `__init__.py` but never used. Org billing uses storage methods directly.
- **Fix:** Delete file, remove exports from `__init__.py`.

### 2.3 HIGH — Unused module: `products/billing/src/budget.py`

- **Path:** `products/billing/src/budget.py` (~70 lines)
- **Issue:** `BudgetCap` class and `BudgetCapExceededError` exported but never used. Gateway tools access budget cap operations directly via `ctx.tracker.storage.db`.
- **Fix:** Delete file, remove exports.

### 2.4 HIGH — Unused class: `RatePolicyManager`

- **File:** `products/billing/src/policies.py:34-94` (~60 lines)
- **Issue:** Exported but never instantiated. Rate limiting handled in `gateway/src/deps/rate_limit.py`.
- **Fix:** Delete class, remove export.

### 2.5 HIGH — Unused identity methods (~11 methods)

- **File:** `products/identity/src/api.py`
- **Methods never called from gateway:**
  - `reveal_commitment()` (line 268)
  - `revoke_attestation()` (line 307)
  - `create_sub_identity()` (line 509)
  - `get_sub_identity()` (line 561)
  - `list_sub_identities()` (line 568)
  - `delete_sub_identity()` (line 573)
  - `rotate_auditor_key()` (line 597)
  - `get_auditor_key_history()` (line 617)
  - `export_attestation_as_vc()` (line 625)
  - `get_inclusion_proof()` (line 655)
  - `record_payment_signal()` (line 802)
- **Fix:** Delete or mark as `@deprecated` if not planned for near-term use.

### 2.6 MEDIUM — Unused messaging methods

- **File:** `products/messaging/src/api.py`
- **Methods not exposed as gateway tools:**
  - `get_thread()` (line 150)
  - `counter_offer()` (line 198)
  - `accept_negotiation()` (line 236)
  - `reject_negotiation()` (line 272)
- **Fix:** Implement corresponding gateway tools or delete.

### 2.7 MEDIUM — Unused trust methods

- **File:** `products/trust/src/api.py`
- **Methods not exposed as gateway tools:**
  - `get_history()` (line 104)
  - `list_servers()` (line 214)
- **Fix:** Implement corresponding gateway tools or delete.

### 2.8 MEDIUM — Unused identity observability functions

- **File:** `products/identity/src/observability.py`
- **Unused functions:**
  - `compute_delta()` (line 31)
  - `detect_trend()` (line 75)
  - `evaluate_alerts()` (line 161)
- **Fix:** Delete unless reserved for future alerting features.

---

## 3. Scripts & Configuration

### 3.1 CRITICAL — `monitoring/.env` tracked in git

- **File:** `monitoring/.env`
- **Issue:** Contains Tailscale IP address (`100.116.117.117`). Currently tracked by git (shows in `git status` as untracked, but is not in `.gitignore`).
- **Fix:** Add `monitoring/.env` to `.gitignore`. If already committed, remove from tracking with `git rm --cached`.

### 3.2 CRITICAL — `.hypothesis/` not in `.gitignore`

- **File:** `.hypothesis/` directory
- **Issue:** Created by Hypothesis testing library. Present as untracked directory but not gitignored — could accidentally be committed.
- **Fix:** Add `.hypothesis/` to `.gitignore`.

### 3.3 HIGH — Legacy deployment script

- **File:** `scripts/deploy_a2a.sh`
- **Issue:** Never called from CI workflows. Replaced by `scripts/deploy.sh` (used in staging.yml, deploy-production.yml).
- **Fix:** Verify not used for manual deployments, then delete or archive.

### 3.4 MEDIUM — Possibly redundant scripts

- **File:** `scripts/deploy_healthcheck.sh` — health check logic is inlined in `deploy.sh`
- **File:** `scripts/deploy_website.sh` — called only by `deploy_a2a.sh` (itself possibly orphaned)
- **Fix:** Verify no manual usage, consolidate or remove.

### 3.5 MEDIUM — `scripts/ci/quality.sh` not used by CI

- **File:** `scripts/ci/quality.sh`
- **Issue:** Not called by any CI workflow (quality checks are inline in `ci.yml`). May be a local development helper.
- **Fix:** Document as local-only or integrate into CI.

---

## 4. Test Issues

### 4.1 HIGH — Unused test fixtures (4 fixtures across 3 modules)

| Fixture | File | Line |
|---------|------|------|
| `sample_probe_target()` | `products/reputation/tests/conftest.py` | 75 |
| `sample_trust_probe_result()` | `products/reputation/tests/conftest.py` | 86 |
| `billing_db()` | `products/payments/tests/conftest.py` | 68 |
| `billing_storage()` | `products/payments/tests/conftest.py` | ~70 |
| `tmp_db()` | `products/paywall/tests/conftest.py` | 71 |

**Note:** Reputation fixtures become moot if the entire `products/reputation/` module is deleted (2.1).

### 4.2 MEDIUM — Duplicate test coverage

- `test_admin_bypasses_ownership` in both `test_tool_context.py` and `test_security_audit.py`
- SQL validator overlap between `test_sql_validator.py` and `test_pg_execute_security.py`
- Error response overlap between `test_error_envelope.py` and `test_problem_details.py`

### 4.3 LOW — Missing test categorization markers

- No `@pytest.mark` markers distinguishing unit vs integration tests.

---

## 5. Markdown Organization

### 5.1 CRITICAL — Duplicate task files

| File | Location A | Location B | Fix |
|------|-----------|-----------|-----|
| `cloudflare-settings.md` | `tasks/active/` | `tasks/done/` | Remove from `tasks/active/` |
| `improve-coverage.md` | `tasks/backlog/` | `tasks/done/` | Remove from `tasks/backlog/` |

### 5.2 CRITICAL — Undocumented `tasks/external/` directory

- **Path:** `tasks/external/` (4 files: `audit.md`, `external-audit-results.v0.8.4.md`, `external-audit-results_0401.md`, `external-full-audit-results.v0.8.4.md`)
- **Issue:** Not documented in CLAUDE.md directory layout.
- **Fix:** Add to CLAUDE.md, or move to `reports/external/` (these are analysis output, not task queue items).

### 5.3 HIGH — Missing `SECURITY.md`

- Referenced in project memory as containing "10 verified findings" but does not exist at repo root.
- **Fix:** Create or locate the security findings report.

### 5.4 HIGH — Metadata files at task queue root

- `tasks/_INSTRUCTIONS_FOR_CLAUDE.md` — should be hidden (`.INSTRUCTIONS_FOR_CLAUDE.md`) or moved to `docs/`
- `tasks/scratchpad.md` — should be in `plans/` or hidden

### 5.5 MEDIUM — Stale active tasks

- `tasks/active/audit-remediation-v0.8.4.md` — check if still in-progress
- `tasks/active/review-external-security-audit.md` — check if still in-progress
- `tasks/active/cloudflare-settings.md` — duplicate (see 5.1)

### 5.6 MEDIUM — Missing standard repo files

- `CONTRIBUTING.md` — best practice for team projects
- `LICENSE` — needed if open-sourcing

---

## Recommended Action Plan

### Immediate (P0) — ~30 min

1. Add `.hypothesis/` and `monitoring/.env` to `.gitignore`
2. Remove duplicate task files (`tasks/active/cloudflare-settings.md`, `tasks/backlog/improve-coverage.md`)
3. Delete `products/reputation/` (entirely orphaned, ~1,500 lines)

### Short-term (P1) — ~1 hour

4. Delete unused billing modules: `org_billing.py`, `budget.py`, `RatePolicyManager` class (~380 lines)
5. Fix `calculate_tool_cost` duplication (keep in `deps/billing.py`, remove from `execute.py`)
6. Delete `check_balance` from `deps/billing.py`
7. Delete `get_tools_by_service` from `catalog.py`
8. Document or reorganize `tasks/external/`
9. Move/hide `tasks/_INSTRUCTIONS_FOR_CLAUDE.md` and `tasks/scratchpad.md`

### Medium-term (P2) — ~2 hours

10. Audit and remove unused identity API methods (~11 methods)
11. Decide on unused messaging methods (implement tools or remove)
12. Decide on unused trust methods (implement tools or remove)
13. Remove unused observability functions
14. Consolidate or clarify rate limit header duplication
15. Clean up legacy deployment scripts (`deploy_a2a.sh`, `deploy_website.sh`, `deploy_healthcheck.sh`)
16. Remove unused test fixtures
17. Create `SECURITY.md`

---

*Report generated by automated codebase audit. All findings should be verified by a human before acting on deletions.*
