# Prompt

## Tasks
Address the following findings from the latest audits:
* "Integration tests run on-demand only (not in main CI loop)" -- Implement integration tests to run before each merge into `main`.
* "No post-package smoke test (install .deb → exercise endpoints)" -- The release pipeline does have `smoke` job after the deployment but running the smoke test before deployment would help catch issues sooner.
*

## Completed
Date: 2026-04-05
Branch: fix/audit-h2-m4-m5 (commit e2bd5e4)

### `integration` job (runs on every PR, blocks staging)
- New CI job starts the gateway from source, provisions an admin API key
  against the live data dir, and runs `scripts/ci/integration_smoke.py`.
- Smoke script is stdlib-only (no extra deps), exercises 16 checks:
  public endpoints (5), auth enforcement (1), billing (2), payment
  intent create + refund incl. `gateway_fee` round-trip (6), RFC 9457
  error shape (2).
- Picked a dedicated smoke script instead of reusing `e2e_tests.py` —
  the latter has ~13 pre-existing failures against a fresh empty DB
  (assumes seeded agents / historical data that CI won't have).

### `smoke-package` job (runs after `package`, blocks staging)
- New CI job extracts the built `.deb` with `dpkg-deb -x`, verifies the
  file layout (main.py, app.py, pricing.json, systemd unit), creates a
  minimal `.env`, starts uvicorn directly against the extracted content,
  and probes 5 public endpoints.
- Catches packaging regressions BEFORE we ship a bad `.deb` to staging,
  rather than after (where `smoke` previously ran against a deployed
  staging host).

### Staging gating
- `staging` job's `needs:` now includes `integration` and `smoke-package`
  alongside quality/test/coverage/package. Broken package or broken
  integration now blocks merge, not just staging deploy.

### Incidental fix
- `scripts/ci/provision_admin_key.py` had an import-order bug:
  `billing_src`/`paywall_src` were imported before
  `gateway.src.bootstrap`, so the namespace packages weren't registered
  in time. Swapped the import order.

### Files changed
- `.github/workflows/ci.yml` — added integration + smoke-package jobs
- `scripts/ci/integration_smoke.py` — new, stdlib-only smoke script
- `scripts/ci/smoke_test_deb.sh` — new, extracts .deb + probes endpoints
- `scripts/ci/provision_admin_key.py` — import-order fix
