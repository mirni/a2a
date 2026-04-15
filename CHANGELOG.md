# Changelog

# Release v1.4.6

**Date:** 2026-04-15
**Commit:** 58564b59
**Previous:** v1.4.5

## Changes

### Bug Fixes

- fix: gatekeeper Z3 reliability — 5 permanent fixes (#113) (`58564b5`)

### Other

- Merge release v1.4.5 into main (`5703338`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | {{VERSION}} |
| a2a-db-backup | {{VERSION}} |
| a2a-gateway | {{VERSION}} |
| a2a-gateway-sandbox | {{VERSION}} |
| a2a-gateway-test | {{VERSION}} |
| a2a-litestream | {{VERSION}} |
| a2a-website | {{VERSION}} |
---


# Release v1.4.5

**Date:** 2026-04-14
**Commit:** 9c5b3ca3
**Previous:** v1.4.2

## Changes

### Features

- feat: add coverage badge to README via CI (#107) (`9baf0be`)

### Bug Fixes

- fix: v1.4.4 audit remediation (F2-F8) (#112) (`9c5b3ca`)
- fix: idempotency collision check reads key from body field too (#111) (`8775f98`)
- fix: stash before checkout in coverage badge push (#110) (`821879b`)
- fix: use /v1/register for stress test agent provisioning (#109) (`421119f`)
- fix: tolerate 403 in stress test when no admin key provided (#108) (`ff2646d`)
- fix(ci): resolve Semgrep shell injection finding in nightly-stress (#106) (`88194b2`)
- fix(stress): per-agent provisioning to eliminate 403 errors (#105) (`b323e0b`)

### Chores

- chore(mcp): bump version to 1.0.0 (#104) (`cc267bf`)

### Other

- Merge release v1.4.2 into main (`919e8d5`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | {{VERSION}} |
| a2a-db-backup | {{VERSION}} |
| a2a-gateway-sandbox | {{VERSION}} |
| a2a-gateway-test | {{VERSION}} |
| a2a-gateway | {{VERSION}} |
| a2a-litestream | {{VERSION}} |
| a2a-website | {{VERSION}} |
---


# Release v1.4.2

**Date:** 2026-04-13
**Commit:** f65f831f
**Previous:** v1.4.1

## Changes

### Bug Fixes

- fix(gatekeeper): credential probe + sandbox mock mode (#103) (`f65f831`)

### Other

- Merge release v1.4.1 into main (`663b5d0`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | {{VERSION}} |
| a2a-db-backup | {{VERSION}} |
| a2a-gateway | {{VERSION}} |
| a2a-gateway-sandbox | {{VERSION}} |
| a2a-gateway-test | {{VERSION}} |
| a2a-litestream | {{VERSION}} |
| a2a-website | {{VERSION}} |
---


# Release v1.4.1

**Date:** 2026-04-13
**Commit:** 9ee96b7f
**Previous:** v1.4.0

## Changes

### Bug Fixes

- fix(gatekeeper): eager boto3 probe + audit remediation plan (#102) (`aa6af71`)

### Documentation

- docs: update distribution queue status, add next-steps analysis (`09a1f3d`)

### Chores

- chore: repo hygiene — gitignore gaps, stale editor files (`2faa4e7`)

### Other

- Merge branch 'main' of https://github.com/mirni/a2a (`9ee96b7`)
- Merge release v1.4.0 into main (`c2755a2`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | {{VERSION}} |
| a2a-db-backup | {{VERSION}} |
| a2a-gateway | {{VERSION}} |
| a2a-gateway-sandbox | {{VERSION}} |
| a2a-gateway-test | {{VERSION}} |
| a2a-litestream | {{VERSION}} |
| a2a-website | {{VERSION}} |
---


# Release v1.4.0

**Date:** 2026-04-13
**Commit:** 25c9bb6b
**Previous:** v1.3.2

## Changes

### Features

- feat(atlas): add Atlas Discovery & Brokering MVP (v1.4.0) (#98) (`e95aadb`)

### Bug Fixes

- fix(gatekeeper): deploy config + CI smoke test for Z3 verifier (#100) (`25c9bb6`)
- fix(audit): v1.3.2 remediation — 4 findings fixed (#99) (`9b72323`)

### Other

- Merge release v1.3.2 into main (`fccdb2c`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | {{VERSION}} |
| a2a-db-backup | {{VERSION}} |
| a2a-gateway | {{VERSION}} |
| a2a-gateway-sandbox | {{VERSION}} |
| a2a-gateway-test | {{VERSION}} |
| a2a-litestream | {{VERSION}} |
| a2a-website | {{VERSION}} |
---


# Release v1.3.2

**Date:** 2026-04-12
**Commit:** 8843314d
**Previous:** v1.3.1

## Changes

### Bug Fixes

- fix(audit): v1.3.1 remediation — 5 findings fixed (v1.3.2) (#97) (`aea7d3b`)

### Tests

- fix(audit): v1.3.1 remediation — 5 findings fixed (v1.3.2) (#97) (`aea7d3b`)

### Other

- Append to master log (`8843314`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | {{VERSION}} |
| a2a-db-backup | {{VERSION}} |
| a2a-gateway | {{VERSION}} |
| a2a-gateway-sandbox | {{VERSION}} |
| a2a-gateway-test | {{VERSION}} |
| a2a-litestream | {{VERSION}} |
| a2a-website | {{VERSION}} |
---


# Release v1.2.8

**Date:** 2026-04-11
**Commit:** baf387e7
**Previous:** v1.2.7

## Changes

### Features

- feat(release): CI Docker publish + decouple deploy/publish + website stats placeholders (#89) (`baf387e`)

### Other

- Merge release v1.2.7 into main (`6018a19`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.8 |
| a2a-db-backup | 1.2.8 |
| a2a-gateway | 1.2.8 |
| a2a-gateway-sandbox | 1.2.8 |
| a2a-gateway-test | 1.2.8 |
| a2a-litestream | 1.2.8 |
| a2a-website | 1.2.8 |
---


# Release v1.2.7

**Date:** 2026-04-11
**Commit:** 4998530d
**Previous:** v1.2.6

## Changes

### Bug Fixes

- fix(ci): use per-package collaborators for NPM_TOKEN preflight (`01824f3`)

### Chores

- chore(sdk): drop @a2a/sdk alias — scope never registered (#88) (`4998530`)

### Other

- Merge release v1.2.6 into main (`e9cfcce`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.7 |
| a2a-db-backup | 1.2.7 |
| a2a-gateway | 1.2.7 |
| a2a-gateway-sandbox | 1.2.7 |
| a2a-gateway-test | 1.2.7 |
| a2a-litestream | 1.2.7 |
| a2a-website | 1.2.7 |
---


# Release v1.2.6

**Date:** 2026-04-11
**Commit:** 3b4a9e65
**Previous:** v1.2.5

## Changes

### Bug Fixes

- fix(ci): pre-flight NPM_TOKEN check + verify sandbox-parity gate (#87) (`3b4a9e6`)

### Tests

- fix(ci): pre-flight NPM_TOKEN check + verify sandbox-parity gate (#87) (`3b4a9e6`)

### Other

- Merge release v1.2.5 into main (`b9178fc`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.6 |
| a2a-db-backup | 1.2.6 |
| a2a-gateway | 1.2.6 |
| a2a-gateway-sandbox | 1.2.6 |
| a2a-gateway-test | 1.2.6 |
| a2a-litestream | 1.2.6 |
| a2a-website | 1.2.6 |
---


# Release v1.2.5

**Date:** 2026-04-11
**Commit:** 36f0083f
**Previous:** v1.2.4

## Changes

### Bug Fixes

- fix(audit-v1.2.4): P0 remediation — admin gate, 410, idempotency, budget, deposits, health SLO (#84) (`727ce85`)

### Tests

- test(audit-v1.2.4): P1 meta-tests — multi-tenant, route enum, sandbox parity, OpenAPI diff (#85) (`36f0083`)

### Other

- Merge release v1.2.4 into main (`99a0d78`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.5 |
| a2a-db-backup | 1.2.5 |
| a2a-gateway | 1.2.5 |
| a2a-gateway-sandbox | 1.2.5 |
| a2a-gateway-test | 1.2.5 |
| a2a-litestream | 1.2.5 |
| a2a-website | 1.2.5 |
---


# Release v1.2.4

**Date:** 2026-04-11
**Commit:** 34ada4d7
**Previous:** v1.2.1

## Changes

### Features

- feat: P0/P1 arch remediation + CMO W1-2 + gatekeeper repricing (v1.2.4) (#82) (`f833533`)
- feat(distribution): A1 — ship MCP server (Python + TS) + registry infra (#78) (`7c1795c`)

### Bug Fixes

- fix(ci): install z3-solver in release workflow test-gateway (#83) (`34ada4d`)
- fix(audit-v1.2.2): remediate CRIT-1..4 + HIGH-1..8 for v1.2.3 (#81) (`78950a9`)
- fix(gateway): annotate disputes schema migration for semgrep (#80) (`7fbcda8`)

### Tests

- fix(audit-v1.2.2): remediate CRIT-1..4 + HIGH-1..8 for v1.2.3 (#81) (`78950a9`)

### Other

- v1.2.2: audit remediation + Gatekeeper JSON policy DSL (#79) (`f3902fd`)
- Merge release v1.2.1 into main (`1c59086`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.4 |
| a2a-db-backup | 1.2.4 |
| a2a-gateway | 1.2.4 |
| a2a-gateway-sandbox | 1.2.4 |
| a2a-gateway-test | 1.2.4 |
| a2a-litestream | 1.2.4 |
| a2a-website | 1.2.4 |
---


# Release v1.2.4

**Date:** 2026-04-11
**Commit:** f8335335
**Previous:** v1.2.1

## Changes

### Features

- feat: P0/P1 arch remediation + CMO W1-2 + gatekeeper repricing (v1.2.4) (#82) (`f833533`)
- feat(distribution): A1 — ship MCP server (Python + TS) + registry infra (#78) (`7c1795c`)

### Bug Fixes

- fix(audit-v1.2.2): remediate CRIT-1..4 + HIGH-1..8 for v1.2.3 (#81) (`78950a9`)
- fix(gateway): annotate disputes schema migration for semgrep (#80) (`7fbcda8`)

### Tests

- fix(audit-v1.2.2): remediate CRIT-1..4 + HIGH-1..8 for v1.2.3 (#81) (`78950a9`)

### Other

- v1.2.2: audit remediation + Gatekeeper JSON policy DSL (#79) (`f3902fd`)
- Merge release v1.2.1 into main (`1c59086`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.4 |
| a2a-db-backup | 1.2.4 |
| a2a-gateway | 1.2.4 |
| a2a-gateway-sandbox | 1.2.4 |
| a2a-gateway-test | 1.2.4 |
| a2a-litestream | 1.2.4 |
| a2a-website | 1.2.4 |
---


# Release v1.2.3

**Date:** 2026-04-10
**Previous:** v1.2.2

## Highlights

Remediation of the v1.2.2 multi-persona black-box audit (4 CRIT + 8 HIGH
findings). No schema migration required; the branch ships as a
backwards-compatible patch release.

- **Gatekeeper / Verifier (CRIT-1, T-1)** — `GatekeeperAPI.submit_job`
  now refuses to start a job when no verifier backend is wired. The
  gateway lifespan auto-selects `MockVerifierClient` when
  `VERIFIER_AUTH_MODE=mock` (CI / local) and falls back cleanly with a
  warning when Lambda credentials are missing, so `/v1/gatekeeper/jobs`
  can no longer hand out "pending forever" job IDs.
- **Gatekeeper billing (CRIT-2, T-2)** — jobs that end in a FAILED /
  TIMEOUT / ERROR state no longer charge the caller. The per-call cost
  is waived *before* the wallet is debited and reflected in the
  `/jobs/{id}` response, so integrators can reconcile without a
  disputes roundtrip.
- **API-key management (HIGH-1, T-3)** — `list_api_keys` now returns
  `agent_id` and `owner_agent_id` so admins can attribute keys to their
  caller without a follow-up lookup.
- **RBAC hardening (HIGH-2, T-4)** — enterprise-tier callers are no
  longer silently promoted to `admin` for `admin_audit_log`; the tool
  now requires an explicit admin tier. Regression test added.
- **SDK release (HIGH-3, T-5)** — `a2a-greenhelix-sdk` 1.2.2 was
  republished to PyPI with the CRIT-1/CRIT-2 client fixes and a new
  `gatekeeper.submit_job(..., wait=True)` convenience helper.
- **Key rotation UX (HIGH-4, T-6)** — `rotate_key` keeps the revoked
  key valid for a 5-minute grace window and returns `rotated_at`,
  `expires_at`, and a human-readable `confirmation` field so clients
  can complete in-flight requests before cutting over.
- **Exchange rate coverage (HIGH-5, T-7)** — `ExchangeRateService` now
  seeds CREDITS↔ETH and CREDITS↔BTC rates on startup and converts
  balances at 18-decimal precision (`Decimal` quantization per asset)
  so `USD→ETH` / `USD→BTC` no longer truncates dust.
- **Refund fee policy (HIGH-6, T-8)** — refund responses include a
  structured `fee_policy` object citing **ADR-011** (`retain_gateway_fee`).
  The 2% gateway fee is retained on refund; integrators can display the
  policy URL to their end users.
- **Identity auto-bind (HIGH-7, T-9)** — API-key provisioning now
  invokes a `KeyManager.on_key_created` callback that auto-registers
  the agent identity and seeds a baseline reputation. New integrators
  no longer have to POST `/v1/identity/agents` before they can sign
  their first request. `IdentityAPI.register_agent` is idempotent when
  called with no key (or the already-stored key); a *conflicting*
  public_key still raises to prevent silent key overwrite.

## Files touched

- `gateway/src/lifespan.py`, `gateway/src/tools/gatekeeper.py`,
  `gateway/src/tools/infrastructure.py`, `gateway/src/tools/payments.py`,
  `gateway/src/tools/identity.py`
- `products/gatekeeper/src/api.py`, `products/gatekeeper/src/billing.py`
- `products/connectors/verifier/src/client.py` (+ `MockVerifierClient`)
- `products/paywall/src/keys.py` (KeyManager.on_key_created hook)
- `products/paywall/src/rotation.py` (+ grace window)
- `products/identity/src/api.py` (idempotent register_agent)
- `products/billing/src/exchange.py` (CREDITS↔ETH/BTC seeding)
- **new** `docs/adr/011-refund-fee-policy.md`
- **new** `gateway/tests/v1/test_audit_v1_2_2_regressions.py` (13 tests)

## Components

| Package | Version |
|---------|---------|
| a2a-gateway | 1.2.3 |
| a2a-greenhelix-sdk | 1.2.3 |

## Upgrade notes

- No DB migration required.
- Set `VERIFIER_AUTH_MODE=mock` for CI / local dev if you don't have
  Lambda credentials. Production deployments keep the default
  (`iam`).
- Integrators that used to swallow `409 AgentAlreadyExistsError` from
  `POST /v1/identity/agents` can now drop that branch — the call is
  idempotent when no public_key is supplied.

---

# Release v1.2.2

**Date:** 2026-04-10
**Previous:** v1.2.1

## Highlights

- **Security (CRIT-2/3/4)** — `/v1/batch` now runs every sub-call through
  the same ownership authorisation and admin-gate as `/v1/execute`. A
  free-tier caller can no longer enumerate another agent's keys,
  wallets, or admin tools via the batch envelope.
- **Reliability (HIGH-4/6)** — `DisputeEngine.connect()` and
  `WebhookManager.connect()` migrate legacy SQLite schemas in-place so
  `/v1/disputes` and `/v1/infra/webhooks` no longer 500 on upgraded
  deployments.
- **Reliability (HIGH-5)** — `ExchangeRateService.get_rate()` routes
  cross-currency pairs through CREDITS as a pivot, so
  `/v1/billing/wallets/{id}/convert USD→ETH` returns a rate instead of
  500. `UnsupportedCurrencyError` is now mapped to HTTP 422.
- **Billing correctness (HIGH-2/3)** — payment intents serialise
  `gateway_fee` via `Decimal.quantize(Decimal("0.01"))` (no more
  `"0.0246"` float leakage); refund responses disclose `fee_refunded` /
  `fee_retained` so integrators can reconcile fee retention.
- **Gatekeeper billing (CRIT-2, gatekeeper domain)** — verification jobs
  that end in a FAILED / TIMEOUT / ERROR state no longer charge the
  caller: the per-call cost is waived before the wallet is debited.
- **Gatekeeper JSON policy DSL** — `language="json_policy"` is now
  accepted on `PropertySpec`. Integrators can submit structured
  invariants (`{op, args, variables}`) that are compiled deterministically
  to SMT-LIB2 on the server. Raw `z3_smt2` remains supported. Five
  example policies ship in `products/gatekeeper/policies/examples/` and
  a new guide lives in `docs/infra/GATEKEEPER_JSON_POLICY.md`.
- **Indie DX** — `/v1/onboarding` quickstart steps 3 and 5 now point at
  the REST routes (`/v1/billing/wallets/.../balance`,
  `/v1/marketplace/services?query=...`) instead of the legacy
  `/v1/execute` envelope.

## Files touched

- `gateway/src/routes/batch.py`, `gateway/src/routes/v1/billing.py`,
  `gateway/src/routes/v1/gatekeeper.py`, `gateway/src/routes/onboarding.py`
- `gateway/src/disputes.py`, `gateway/src/webhooks.py`,
  `gateway/src/tools/payments.py`, `gateway/src/errors.py`
- `products/billing/src/exchange.py`
- `products/gatekeeper/src/api.py`, `products/gatekeeper/src/models.py`,
  **new** `products/gatekeeper/src/policy.py`
- **new** `products/gatekeeper/policies/examples/{balance_conservation,withdraw_guard,fee_bounded,escrow_state_machine,rate_limit_ok}.json`
- **new** `docs/infra/GATEKEEPER_JSON_POLICY.md`
- **new** `gateway/tests/v1/test_audit_v1_2_1_regressions.py` (16 regression tests)
- **new** `products/gatekeeper/tests/test_policy.py` (17 tests)

## Components

| Package | Version |
|---------|---------|
| a2a-gateway | 1.2.2 |
| a2a-greenhelix-sdk | 1.2.2 |

---


# Release v1.2.1

**Date:** 2026-04-10
**Commit:** b24b9cb5
**Previous:** v1.2.0

## Changes

### Other

- Update master log with latest PR (merged already) (`b24b9cb`)
- Wire VerifierClient + Lambda tests + audit fixes (#77) (`06c2c21`)
- Merge release v1.2.0 into main (`3fe1b8f`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.1 |
| a2a-db-backup | 1.2.1 |
| a2a-gateway | 1.2.1 |
| a2a-gateway-sandbox | 1.2.1 |
| a2a-gateway-test | 1.2.1 |
| a2a-website | 1.2.1 |
---


# Release v1.2.0

**Date:** 2026-04-09
**Commit:** 26042ce7
**Previous:** v1.1.3

## Changes

### Features

- feat: formal gatekeeper service with Z3 verification (#76) (`26042ce`)

### Other

- Merge release v1.1.3 into main (`00e18e2`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.2.0 |
| a2a-db-backup | 1.2.0 |
| a2a-gateway-sandbox | 1.2.0 |
| a2a-gateway-test | 1.2.0 |
| a2a-gateway | 1.2.0 |
| a2a-website | 1.2.0 |
---


# Release v1.1.3

**Date:** 2026-04-08
**Commit:** 225438fe
**Previous:** v1.1.2

## Changes

### Features

- feat: add /.well-known/agent.json (A2A standard discovery path) (`bdd0761`)
- feat: onboarding improvements + contract/mutation testing setup (`1bc96af`)

### Bug Fixes

- Merge pull request #75 from mirni/feat/onboarding-and-findings (`225438f`)
- fix: sync website/docs.html with catalog v1.1.2 (`33dc83a`)
- fix: remediate SDK audit findings (4 bugs) (`7fdb7f4`)
- fix(ci): reset coverage baseline and remove bad coverage config (`c51202a`)
- fix(ci): exclude test files from coverage measurement (`5dce47a`)
- fix(ci): measure coverage on gateway/src only, not gateway/tests (`761a473`)

### Tests

- fix(ci): exclude test files from coverage measurement (`5dce47a`)

### Chores

- chore: update task files with completion status (`80a7f25`)

### Other

- Merge branch 'main' into feat/onboarding-and-findings (`1f25286`)
- Merge release v1.1.2 into main (`d6ec259`)
- style: format test_contract_models.py with ruff (`7293edd`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.1.3 |
| a2a-db-backup | 1.1.3 |
| a2a-gateway | 1.1.3 |
| a2a-gateway-sandbox | 1.1.3 |
| a2a-gateway-test | 1.1.3 |
| a2a-website | 1.1.3 |
---


# Release v1.1.2

**Date:** 2026-04-08
**Commit:** 295698c6
**Previous:** v1.1.1

## Changes

### Features

- feat: agent onboarding improvements + contract/mutation testing (#74) (`9e12d2c`)
- feat(ci): migrate SDK publishing to GitHub Actions trusted publishing (#72) (`20405ea`)

### Bug Fixes

- fix(ci): remediate shell injection in publish.yml (semgrep) (`295698c`)
- fix(ci): add workflow_dispatch to publish.yml for manual re-publishing (#73) (`c3105d1`)

### Tests

- feat: agent onboarding improvements + contract/mutation testing (#74) (`9e12d2c`)

### Other

- release: v1.1.2 (`ac1ff8e`)
- Update instructions on infra (`ea2aff0`)
- Merge release v1.1.1 into main (`b940d25`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.1.2 |
| a2a-db-backup | 1.1.2 |
| a2a-gateway | 1.1.2 |
| a2a-gateway-sandbox | 1.1.2 |
| a2a-gateway-test | 1.1.2 |
| a2a-website | 1.1.2 |
---


# Release v1.1.2

**Date:** 2026-04-08
**Commit:** ea2aff07
**Previous:** v1.1.1

## Changes

### Features

- feat: agent onboarding improvements + contract/mutation testing (#74) (`9e12d2c`)
- feat(ci): migrate SDK publishing to GitHub Actions trusted publishing (#72) (`20405ea`)

### Bug Fixes

- fix(ci): add workflow_dispatch to publish.yml for manual re-publishing (#73) (`c3105d1`)

### Tests

- feat: agent onboarding improvements + contract/mutation testing (#74) (`9e12d2c`)

### Other

- Update instructions on infra (`ea2aff0`)
- Merge release v1.1.1 into main (`b940d25`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.1.2 |
| a2a-db-backup | 1.1.2 |
| a2a-gateway | 1.1.2 |
| a2a-gateway-sandbox | 1.1.2 |
| a2a-gateway-test | 1.1.2 |
| a2a-website | 1.1.2 |
---


# Release v1.1.1

**Date:** 2026-04-07
**Commit:** a28ef9b0
**Previous:** v1.1.0

## Changes

### Bug Fixes

- fix(sdk): add missing pydantic dep, add post-publish smoke tests (#71) (`bc757bb`)
- fix(sdk-ts): sync package-lock.json name with package.json (@greenhelix/sdk) (`621879d`)
- fix(website): sync docs.html version with catalog (1.1.0) (`8f19eda`)

### Other

- ci: stop running CI on push to main (redundant) (`a28ef9b`)
- Merge release v1.1.0 into main (`36d10d2`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.1.1 |
| a2a-db-backup | 1.1.1 |
| a2a-gateway | 1.1.1 |
| a2a-gateway-sandbox | 1.1.1 |
| a2a-gateway-test | 1.1.1 |
| a2a-website | 1.1.1 |
---


# Release v1.1.0

**Date:** 2026-04-07
**Commit:** 79ccb76b
**Previous:** v1.0.7

## Changes

### Bug Fixes

- fix(onboarding): auto-register identity, add hints, update pricing (#70) (`17efadb`)
- fix(audit): remediate H-REF, M2, M3 from v1.0.7 audit (#69) (`af73be3`)
- fix(release): auto-bootstrap venv and source .env (#68) (`92087bb`)
- fix(release): support publish-only re-runs for existing releases (#67) (`cc57169`)

### Other

- Update master log (`79ccb76`)
- Merge release v1.0.7 into main (`81d3175`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.1.0 |
| a2a-db-backup | 1.1.0 |
| a2a-gateway | 1.1.0 |
| a2a-gateway-sandbox | 1.1.0 |
| a2a-gateway-test | 1.1.0 |
| a2a-website | 1.1.0 |
---


# Release v1.0.7

**Date:** 2026-04-06
**Commit:** 78990b5d
**Previous:** v1.0.6

## Changes

### Bug Fixes

- fix(release): ensure npm and Docker publish with --publish (#66) (`78990b5`)

### Other

- Merge release v1.0.6 into main (`ef8fca5`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.7 |
| a2a-db-backup | 1.0.7 |
| a2a-gateway | 1.0.7 |
| a2a-gateway-sandbox | 1.0.7 |
| a2a-gateway-test | 1.0.7 |
| a2a-website | 1.0.7 |
---


# Release v1.0.6

**Date:** 2026-04-06
**Commit:** 7c992212
**Previous:** v1.0.4

## Changes

### Bug Fixes

- fix(ci): suppress semgrep XXE false positive in merge_coverage_xml.py (#65) (`7c99221`)

### Refactoring

- refactor(ci): shard test-gateway + fix audit findings H-NEW/H-RACE/M2/M3/M4 (#64) (`bc0dafa`)

### Other

- Merge release v1.0.4 into main (`e2f8cc6`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.6 |
| a2a-db-backup | 1.0.6 |
| a2a-gateway | 1.0.6 |
| a2a-gateway-sandbox | 1.0.6 |
| a2a-gateway-test | 1.0.6 |
| a2a-website | 1.0.6 |
---


# Release v1.0.4

**Date:** 2026-04-06
**Commit:** c31062db
**Previous:** v1.0.2

## Changes

### Bug Fixes

- fix(security): CRITICAL BOLA — restrict capture to payer only (#63) (`8466664`)
- fix(ci): move nosemgrep comment to correct line for urllib finding (`3c0b119`)
- fix(security): CRITICAL BOLA — restrict capture to payer only (`4dbf92c`)
- fix(ci): deploy gate, test split, pytest warning (#62) (`21db207`)

### Other

- Merge branch 'release/1.0.3' (`c31062d`)
- release: v1.0.3 (`87aacdd`)
- Merge release v1.0.2 into main (`00d3cee`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.4 |
| a2a-db-backup | 1.0.4 |
| a2a-gateway | 1.0.4 |
| a2a-gateway-sandbox | 1.0.4 |
| a2a-gateway-test | 1.0.4 |
| a2a-website | 1.0.4 |
---


# Release v1.0.3

**Date:** 2026-04-06
**Commit:** 21db2078
**Previous:** v1.0.2

## Changes

### Bug Fixes

- fix(ci): deploy gate, test split, pytest warning (#62) (`21db207`)

### Other

- Merge release v1.0.2 into main (`00d3cee`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.3 |
| a2a-db-backup | 1.0.3 |
| a2a-gateway | 1.0.3 |
| a2a-gateway-sandbox | 1.0.3 |
| a2a-gateway-test | 1.0.3 |
| a2a-website | 1.0.3 |
---


# Release v1.0.2

**Date:** 2026-04-06
**Commit:** 01f15229
**Previous:** v1.0.1

## Changes

### Bug Fixes

- fix(payments): resolve C2 capture OperationalError + H2 HTTPS enforcement (#61) (`01f1522`)

### Other

- Merge release v1.0.1 into main (`c0e656f`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.2 |
| a2a-db-backup | 1.0.2 |
| a2a-gateway | 1.0.2 |
| a2a-gateway-sandbox | 1.0.2 |
| a2a-gateway-test | 1.0.2 |
| a2a-website | 1.0.2 |
---


# Release v1.0.1

**Date:** 2026-04-06
**Commit:** e2467ca8
**Previous:** v1.0.0

## Changes

### Bug Fixes

- fix(security): remediate audit findings C1, C2, H2 (#60) (`e2467ca`)

### Chores

- chore: rename SDK to a2a-greenhelix-sdk + bump versions to 1.0.0 (`8197a27`)

### Other

- Merge release v1.0.0 into main (`0e2eb4e`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.1 |
| a2a-db-backup | 1.0.1 |
| a2a-gateway | 1.0.1 |
| a2a-gateway-sandbox | 1.0.1 |
| a2a-gateway-test | 1.0.1 |
| a2a-website | 1.0.1 |
---


# Release v1.0.0

**Date:** 2026-04-06
**Commit:** e35f5b17
**Previous:** v0.9.6

## Changes

### Features

- feat(ci): add PG connector live-DB integration tests to CI (#55) (`15be376`)

### Bug Fixes

- fix: audit H2/H3 + M4/M5 docs + CI integration & package smoke jobs (#58) (`b5a94b2`)
- fix: audit remediation — C1-C4/H1/H3/M1-M3 + CTO runbooks + ADRs 002-009 (#57) (`100382f`)

### Documentation

- fix: audit remediation — C1-C4/H1/H3/M1-M3 + CTO runbooks + ADRs 002-009 (#57) (`100382f`)

### Tests

- test: raise billing/payments/paywall coverage to 99% (#56) (`b48a433`)

### Other

- Fix/audit h2 m4 m5 (#59) (`e35f5b1`)
- Merge release v0.9.6 into main (`e513ade`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 1.0.0 |
| a2a-db-backup | 1.0.0 |
| a2a-gateway | 1.0.0 |
| a2a-gateway-sandbox | 1.0.0 |
| a2a-gateway-test | 1.0.0 |
| a2a-website | 1.0.0 |
---


# Release v0.9.6

**Date:** 2026-04-05
**Commit:** 17afcfda
**Previous:** v0.9.3

## Changes

### Bug Fixes

- fix: scope deploy /tmp paths per-component to prevent parallel job race (#53) (`17afcfd`)
- fix: missing jsonschema runtime dep — connector tools return 500 on v0.9.3 (#52) (`240528d`)

### Tests

- fix: missing jsonschema runtime dep — connector tools return 500 on v0.9.3 (#52) (`240528d`)

### Other

- Merge release v0.9.3 into main (`1fb403a`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.9.6 |
| a2a-db-backup | 0.9.6 |
| a2a-gateway | 0.9.6 |
| a2a-gateway-sandbox | 0.9.6 |
| a2a-gateway-test | 0.9.6 |
| a2a-website | 0.9.6 |
---


# Release v0.9.3

**Date:** 2026-04-05
**Commit:** fb703c4e
**Previous:** v0.9.2

## Changes

### Features

- feat: implement all 11 SOC 2 immediate action items (#49) (`82ad4dc`)

### Bug Fixes

- fix: security audit remediation — 27 findings across 4 audit reports (#51) (`fb703c4`)

### Other

- Fix CI warnings, coverage paths, and update .env.example (#50) (`178f315`)
- Merge release v0.9.2 into main (`159c5b1`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.9.3 |
| a2a-db-backup | 0.9.3 |
| a2a-gateway | 0.9.3 |
| a2a-gateway-sandbox | 0.9.3 |
| a2a-gateway-test | 0.9.3 |
| a2a-website | 0.9.3 |
---


# Release v0.9.2

**Date:** 2026-04-04
**Commit:** f3023263
**Previous:** v0.9.1

## Changes

### Features

- feat: post coverage ratchet results as PR comments (#46) (`833d3b0`)
- feat: complete LangChain + CrewAI framework integrations (#44) (`9b96a83`)
- feat: live payments test guide + 3-hour performance stress test (#43) (`c67f25d`)
- Merge pull request #41 from mirni/feat/distribution-implementation (`07661e3`)
- feat: distribution action plan and DISTRIBUTION.md update (`1e07225`)
- feat: implement distribution infrastructure (AGENTS.md, SKILL.md, SDK metadata, agent card) (`3437667`)
- feat: load monitoring/.env for persistent config overrides (`4cd4ead`)

### Bug Fixes

- fix: address market-readiness audit findings (B1, B2, S1–S4) (#48) (`bf85b1d`)
- fix: replace stale @a2a/sdk npm refs with @greenhelix/sdk (#45) (`cdcc032`)
- fix: remove license classifier superseded by PEP 639 license expression (`7f11e20`)
- fix: Stripe dedup DB-first + CI coverage integration (#39) (`612daca`)
- fix: remediate pre-launch audit findings (P0/P1) + DX improvements (#38) (`2a2a1b3`)
- fix: update check_server.sh for current API format (`6bd5fdc`)
- fix: improve monitoring check diagnostics with failure hints (`f1b587c`)
- fix: remove broken health scrape job from Prometheus (`9b1183b`)
- fix: monitoring stack over Tailscale VPN (`23c306c`)

### Refactoring

- refactor: remove ~4,000 lines of dead code (#37) (`56c4205`)

### Documentation

- docs: add market-readiness audit v0.9.1 (#47) (`528ef36`)
- docs: add live payments audit guide for external testing (#42) (`4f6f916`)
- docs: update all public-facing documentation for consistency (#40) (`d4d5dde`)

### Chores

- chore: clean up task queue and add market-readiness audit prompt (`24ad568`)

### Other

- Update the plan with some finished tasks (`f302326`)
- Changes to prometheus.yml config to bypass cloudflare checks (`b5ffb44`)
- Merge release v0.9.1 into main (`1113126`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.9.2 |
| a2a-db-backup | 0.9.2 |
| a2a-gateway | 0.9.2 |
| a2a-gateway-sandbox | 0.9.2 |
| a2a-gateway-test | 0.9.2 |
| a2a-website | 0.9.2 |
---


# Release v0.9.1

**Date:** 2026-04-02
**Commit:** d15d9477
**Previous:** v0.9.0

## Changes

### Bug Fixes

- fix: remediate v0.8.4 security audit findings (6 issues) (#35) (`2058d40`)

### Documentation

- docs: Cloudflare hardening guide for AI agent API (#36) (`7504aee`)

### Other

- Merge branch 'main' of https://github.com/mirni/a2a (`d15d947`)
- Update tasks (`325e8e2`)
- Merge release v0.9.0 into main (`9422e19`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.9.1 |
| a2a-db-backup | 0.9.1 |
| a2a-gateway | 0.9.1 |
| a2a-gateway-sandbox | 0.9.1 |
| a2a-gateway-test | 0.9.1 |
| a2a-website | 0.9.1 |
---


# Release v0.9.0

**Date:** 2026-04-02
**Commit:** d021c7a3
**Previous:** v0.8.4

## Changes

### Other

- Merge release v0.8.4 into main (`d021c7a`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.9.0 |
| a2a-db-backup | 0.9.0 |
| a2a-gateway | 0.9.0 |
| a2a-gateway-sandbox | 0.9.0 |
| a2a-gateway-test | 0.9.0 |
| a2a-website | 0.9.0 |
---


# Release v0.8.4

**Date:** 2026-04-02
**Commit:** d3d98d9e
**Previous:** v0.8.3

## Changes

### Bug Fixes

- fix: add missing migration for currency column on transactions table (`d043f6e`)
- fix: use datetime.UTC import compatible with Python 3.12 (`94f9697`)
- fix: use /opt/a2a as default install dir for generate_audit_keys (`9453a31`)

### Other

- Merge branch 'fix/audit-keys-install-dir' (`d3d98d9`)
- Merge release v0.8.3 into main (`648b69a`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.8.4 |
| a2a-db-backup | 0.8.4 |
| a2a-gateway | 0.8.4 |
| a2a-gateway-sandbox | 0.8.4 |
| a2a-gateway-test | 0.8.4 |
| a2a-website | 0.8.4 |
---


# Release v0.8.3

**Date:** 2026-04-02
**Commit:** 2e5bcd61
**Previous:** v0.8.2

## Changes

### Bug Fixes

- fix: use /opt/a2a as default install dir for generate_audit_keys (#34) (`2e5bcd6`)
- fix: import bootstrap before product modules in generate_audit_keys (#33) (`41304a1`)

### Other

- Merge release v0.8.2 into main (`7875258`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.8.3 |
| a2a-db-backup | 0.8.3 |
| a2a-gateway | 0.8.3 |
| a2a-gateway-sandbox | 0.8.3 |
| a2a-gateway-test | 0.8.3 |
| a2a-website | 0.8.3 |
---


# Release v0.8.2

**Date:** 2026-04-02
**Commit:** 419e6e98
**Previous:** v0.8.1

## Changes

### Other

- Merge release v0.8.1 into main (`419e6e9`)

## Components

| Package | Version |
|---------|---------|
| a2a-common | 0.8.2 |
| a2a-db-backup | 0.8.2 |
| a2a-gateway | 0.8.2 |
| a2a-gateway-sandbox | 0.8.2 |
| a2a-gateway-test | 0.8.2 |
| a2a-website | 0.8.2 |
---


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
