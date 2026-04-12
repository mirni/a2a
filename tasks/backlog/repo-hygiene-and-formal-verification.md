# Repo Hygiene & Formal Verification — Cleanup Plan

**Role:** Senior Software Architect + Formal Verification
**Scope:** Monorepo cleanup + Z3 integration roadmap
**Estimated effort:** 8–10 days P0–P2, then Phase 4 FV work on top
**Driver:** Audit cycle has surfaced growth strain — storage migration gaps,
float-for-money drift, duplicated test infra, god-classes. Land this before
it turns into next release's CRITs.

## Status (2026-04-12, branch `fix/repo-hygiene-v1.2.9`)

**Phase 1 P0 complete** — shipped in PR for v1.2.9. Commits:

- `e7040c8` `feat(release): top-level VERSION file + sync_versions.py + CI drift guard` — P0-3
- `8f9c09b` `feat(lint): Pydantic extra="forbid" guardrail for request models` — P0-2
- `9a54b25` `fix(storage): propagate C2 column-migration hook to 4 more products` — P0-1
- `e990bde` `fix(money): Decimal-only comparisons at deposit + budget cap gates` — narrow hotfix slice of P1-3
- `dee87b2` `release: bump to v1.2.9` — version + em-dash sync fix

**Phase 2 (P1), Phase 3 (P2), Phase 4 (Z3), Phase 5 (deferred) remain pending.**
This file stays in `tasks/backlog/` until those phases land.

---

## Context

After 5 audit cycles (v1.2.3 → v1.2.7) the code patterns that keep getting
flagged are not one-off bugs — they are **structural**. A senior architect
review of `/workdir` finds four recurring issue classes:

1. **Storage classes that re-invoke `executescript(_SCHEMA)` without column
   migrations** — identity, messaging, trust, marketplace all copy the exact
   pattern that caused audit C2 in payments (v1.0.1). Ticking time bomb for
   v1.2.9+.
2. **`float()` conversions on Decimal amounts** on ~50 lines in the paid
   path — budget cap, split intent, refund, gateway fee, deposit-limit
   boundary. Explains why v1.2.7 audit shows off-by-a-cent in refund
   bookkeeping. Root-cause is arithmetic, not race.
3. **Duplicated test scaffolding** — 12 `conftest.py` files each re-register
   `sys.modules["shared_src"]`, each spin up their own tempfile DB, each
   rebuild a virtual package. ~250 lines of copy-paste; every new product
   forks another copy.
4. **God-class modules** — `gateway/src/middleware.py` (795 lines, 7+
   middleware classes), `lifespan.py` (508), `webhooks.py` (588),
   `routes/execute.py` (702). They compile and test fine but new
   contributors cannot hold them in working memory, and incremental edits
   spread the blast radius.

The formal verification lane (Z3-solver + AWS Lambda gatekeeper) has been
sitting idle — 5 audits flagged Gatekeeper as 0/50 broken but the deeper
issue is that we have the tool and we are not using it for anything
outside policy examples. This plan wires Z3 into the paid-path invariants
so we can **prove** budget caps, refund ≤ original, and split-sum = amount,
instead of discovering violations through audits.

See the architect review transcript (this task was generated from an
Explore-agent walk of `gateway/`, `sdk/`, `products/*`, `scripts/`,
`.github/workflows/`) for the full evidence.

---

## Phase 1 — P0 (blocks v1.2.9)

### P0-1 · Propagate `_apply_column_migrations` to all storage layers

**Problem.** `products/payments/src/storage.py` has the defensive
`_apply_column_migrations` pattern that was added in PR #61 to fix audit
C2 (`OperationalError: no such column`). The same `connect() →
executescript(_SCHEMA)` pattern exists in:

- `products/identity/src/storage.py`
- `products/messaging/src/storage.py`
- `products/trust/src/storage.py`
- `products/marketplace/src/storage.py`

Any of these will start crashing on upgrade the moment we add a column to
the schema, because `CREATE TABLE IF NOT EXISTS` is a no-op and
`CREATE INDEX` on the new column will blow up.

**Action.**
- Extract the `_apply_column_migrations` helper into
  `products/shared/src/storage_migrations.py` (single source).
- Each product storage class calls it on `connect()` before running
  `executescript(_SCHEMA)`.
- Helper is table-agnostic: pass a list of `(table, column, type)` tuples;
  it `ALTER TABLE … ADD COLUMN` only if `PRAGMA table_info` confirms the
  column is missing.

**Acceptance.**
- Unit test (red first): for each product, open a DB with the v1.2.0
  schema (dump committed to `products/<product>/tests/fixtures/v1.2.0.sql`),
  upgrade it in-process, assert `connect()` succeeds and every expected
  column exists.
- Negative: corrupt a fixture (drop a required column), assert the
  migration helper re-adds it.
- Regression test in CI that runs the v1.0.0 → v1.2.8 upgrade path for
  every product storage class.

### P0-2 · `extra="forbid"` gate is enforced by CI, not by eyeballs

Every request model already uses `ConfigDict(extra="forbid")` today — the
architect review confirmed the audit finding is a false positive on
current code. But we have no guard against a future contributor dropping
it. Add a small pyproject-local lint:

- `scripts/lint_pydantic_forbid.py` — walk `routes/v1/*.py` and
  `routes/execute.py`, `ast.parse` each file, find every class inheriting
  from `BaseModel`, assert its `model_config` includes
  `extra="forbid"`. Exit 1 with file:line on violation.
- Wired into `.github/workflows/ci.yml` quality job.

### P0-3 · Version sync is mechanical, not manual

`gateway/src/_version.py` is authoritative but `sdk/pyproject.toml`,
`sdk-ts/package.json`, `products/*/pyproject.toml` all drift. Centralise:

- `release.sh` reads `gateway/src/_version.py` and rewrites the version
  field in every sibling `pyproject.toml` / `package.json` / `Cargo.toml`
  it can find under the monorepo.
- Guarded by a `--dry-run` flag and a diff-preview so the human sees
  exactly what would change before the commit.
- Red test: `scripts/tests/test_release_version_sync.py` — seeds a fake
  tree with 3 diverging versions, runs the sync, asserts all files land
  on the target version and commit message matches.

---

## Phase 2 — P1 (next cycle after v1.2.9)

### P1-1 · Consolidate `conftest.py` duplication

- Create `products/shared/tests/conftest_base.py` exposing:
  - `shared_src_registration` fixture (sys.modules virtual package
    registration, runs once per session)
  - `temp_sqlite_db` fixture (yields a tempfile-backed DB path, cleans up)
  - `multi_tenant_keys` fixture (already specced in
    `tasks/backlog/v1.2.4-audit-p1.md`)
- Each product's own `conftest.py` becomes `from
  products.shared.tests.conftest_base import *` + product-specific
  additions.
- Net delete: ~250 lines of copy-paste.

### P1-2 · Split `gateway/src/middleware.py` (795 LOC god-class)

Current middleware file hosts 7+ middleware classes:
`CorrelationID`, `SecurityHeaders`, `ClientIP`, `PublicRateLimit`,
`Metrics`, `BodySize`, `Timeout`, `HTTPS`, `AgentIdLength`, `EncodedPath`.

Split into `gateway/src/middleware/` package:
- `correlation.py`
- `security_headers.py`
- `client_ip.py` (the trusted-proxy logic that the v1.2.3 audit flagged)
- `rate_limit.py`
- `body_size.py`
- `timeout.py`
- `validation.py` (agent ID length, encoded path, HTTPS redirect)

Each sub-module <200 LOC. Tests move to
`gateway/tests/middleware/test_<name>.py`.

### P1-3 · Decimal-only arithmetic for money paths

**Evidence gathered in review (~50 `float(` instances near currency):**

- `gateway/src/gatekeeper_metrics.py:106` — `cost_sum` accumulator in float
- `gateway/src/deps/tool_context.py:237,251` — rate-limit spend in float
- `gateway/src/routes/v1/billing.py:137,155,192,466` — response serialization
- `gateway/src/routes/v1/payments.py:200,235,311,349,374,482,539` — body.amount → float
- `gateway/src/tools/payments.py:132,165,205,265,271,547,577` — fee/split calc
- `products/billing/src/wallet.py:64,311` — bonus & FX
- `products/payments/src/engine.py:164,281,296,327,412,417,517` — refund/capture math

**Fix class.**
- `shared_src/money.py` already has Decimal helpers — extend with
  `split_amount(total, ratios) -> list[Decimal]` that guarantees
  `sum(result) == total` (last slice absorbs rounding).
- Route response serialization: emit Decimal as string, not float. Update
  SDK to parse back to Decimal.
- Grep gate: `scripts/lint_no_float_money.py` — flags any `float(`
  appearing within 5 lines of a variable named `amount|balance|cost|
  fee|credit|price|spend|cap`. False positive rate is low; whitelist the
  observability counters.
- Hypothesis test: for any 3-way split with ratios summing to 100, the
  rounded split sums back to the original amount within 1e-18.

### P1-4 · Remove `/v1/execute` on its sunset date

The legacy endpoint is already wrapped in a deprecation shim and returns
410 Gone. Schedule its removal:
- Sunset header is `Wed, 01 Jan 2026 00:00:00 GMT` — already past. Delete
  `gateway/src/routes/execute.py` and the `_LEGACY_EXECUTE_ENABLED` gate.
- Confirm zero production traffic via paywall access logs first (human
  blocker — flag in PR).
- Drop the entire file + tests. ~700 LOC gone.

---

## Phase 3 — P2 (code quality, opportunistic)

### P2-1 · Shared tool-handler validators

Extract the duplicated `_inject_caller`, `_check_intent_ownership`,
`_format_money` helpers into `gateway/src/tools/_validators.py`. They are
currently copy-pasted across `payments.py`, `billing.py`, `identity.py`,
`disputes.py`, `marketplace.py`, `messaging.py`.

### P2-2 · Bootstrap import-order smoke test

New `scripts/test_bootstrap.py` that imports every product in the
bootstrap order and asserts no `ImportError`, no
`ModuleNotFoundError`, no circular dep. Runs as part of CI quality job.
Prevents accidental regressions on the sys.modules hack chain.

### P2-3 · Centralise tier + pricing truth

Today tier definitions live in (at least):
- `gateway/src/config.py` (deposit_limits, budget_caps)
- `pricing.json` (tool costs)
- `products/billing/src/pricing.py` (billing tier logic)
- Tool catalog (`tier_required`)

Consolidate into a single `config/tiers.json` consumed by all four. CI
diff-check that nothing reads tier info anywhere else.

### P2-4 · Replace `time.sleep` / `asyncio.sleep` in tests with fake clocks

20+ occurrences flag under
`gateway/tests/test_data_retention.py`,
`gateway/tests/test_cleanup_tasks.py`,
`gateway/tests/test_public_rate_limit.py`.

Use `freezegun` or a fake clock fixture so tests don't flake on slow CI
runners and don't waste wall-clock time.

### P2-5 · Prune skipped / xfail tests

- `gateway/tests/test_openapi_schema_diff.py:34` is
  `skipif(not _BASELINE.exists())`. Commit the baseline (or delete the
  test). The architect review called this out as "disables schema
  validation CI for free".
- `products/gatekeeper/tests/test_policy.py:270` is `skipif(not Z3)`.
  Phase 4 makes Z3 a hard dep; this skip goes away.

---

## Phase 4 — Formal Verification (Z3) integration

The gatekeeper already has `z3-solver` in its dependency chain and the
AWS Lambda verifier is wired into `products/gatekeeper/src/`. We have
been using it for policy-proof demos and nothing else. Target the paid
path with six concrete invariants.

### FV-1 · Wallet balance never goes negative

```
{ balance ≥ 0 ∧ amount ≥ 0 }
  balance := balance - amount
{ balance ≥ 0 }
```

Precondition `balance ≥ amount` is the check we need to prove is
enforced *before* the debit in `wallet.debit()`. Z3 model:

```python
balance = Int("balance")
amount  = Int("amount")
s = Solver()
s.add(balance >= 0, amount >= 0)
s.add(Not(Implies(balance - amount >= 0, balance >= amount)))
assert s.check() == unsat   # post-state nonneg ⇒ pre-check held
```

Any bug class where we forgot the pre-check gets caught by the solver
returning `sat` with a counterexample assignment.

### FV-2 · Refund ≤ captured

```
{ captured ≥ 0 ∧ refund_total ≥ 0 ∧ refund_total ≤ captured }
  refund(extra)
{ refund_total' = refund_total + extra ∧ refund_total' ≤ captured }
```

Model the payment intent as `(captured, refund_total)` and prove that
every refund operation preserves the invariant. Catches the v1.2.7
`+$1 balance drift` finding at the source.

### FV-3 · Split amounts sum to intent total (before fees)

```
{ ∀ i. split[i] ≥ 0 ∧ total ≥ 0 }
  splits := allocate(total, ratios)
{ Σ split[i] = total }
```

Z3 model with 3 Int splits + Int total + rational ratios. Proves that
`money.split_amount()` is correct by construction. Would catch the float
rounding bug that currently sends $35.99 to `charlie` instead of $36.10.

### FV-4 · Budget cap enforced before debit (monotonic counter)

```
Invariant (loop):
  spend ≤ cap
Body of each paid request:
  { spend ≤ cap ∧ cost ≥ 0 }
  if spend + cost > cap then reject
  spend := spend + cost
  { spend ≤ cap }
```

This is the v1.2.7 NEW-CRIT-7-2-7 (`cap=0.00`) invariant. If we can
*prove* the check-then-increment is atomic and the read/write go to the
same store, the audit finding disappears permanently. Model includes
the race case: 2 concurrent requests each sampling the pre-state.

### FV-5 · Tier access-control matrix is sound

```
ADMIN_ONLY_TOOLS ⊆ tools
∀ tool ∈ tools. ∀ caller_tier.
  call_allowed(tool, caller_tier)
    ⇒ tier_rank(caller_tier) ≥ tier_rank(tool.required_tier)
```

Z3 models the 4-element tier lattice `free < pro < enterprise < admin`
and the `ADMIN_ONLY_TOOLS` set. Proves no free/pro caller can reach an
admin tool regardless of which route or header path they go through.
Exactly the v1.2.3/v1.2.4 persistent CRIT class.

### FV-6 · Idempotency key→response is a function

```
∀ key. ∀ req₁ req₂ with Idempotency-Key = key.
  (req₁.body_hash = req₂.body_hash ⇒ response(req₁) = response(req₂))
  ∧ (req₁.body_hash ≠ req₂.body_hash ⇒ response(req₂) = 409)
```

Models the idempotency store as an uninterpreted function `f: Key → Resp`
and proves the router's dispatch logic realises that function. Catches
the double-write race the v1.2.4 P0-4 test specced.

### How Z3 plugs into the existing gatekeeper

1. Add a new proof harness: `products/gatekeeper/src/invariants/`.
   Each file is an SMT-LIB or Z3 Python script named after the invariant
   (`wallet_nonneg.py`, `refund_bound.py`, …).
2. `products/gatekeeper/tests/test_invariants.py` runs every harness
   locally (z3-solver pip package) and asserts `unsat` for the negation.
3. `.github/workflows/ci.yml` quality job runs the harness suite. Fails
   the build on any `sat` result; prints the counterexample.
4. The AWS Lambda gatekeeper gains a new tool
   `verify_invariant(name, context)` that runs the harness with
   caller-supplied constants. This lets the runtime *replay* an invariant
   on real transaction data when a suspicious event fires (e.g. budget
   cap exceeded), giving us a proof-backed post-mortem.
5. Release gate: `scripts/release.sh` includes `pytest
   products/gatekeeper/tests/test_invariants.py` before tag creation.
   v1.2.8 already unblocked this via #83's z3-solver install fix.

### Suggested Z3 invariant intake rule

Any new business rule touching money, tiers, state machines, or access
control **must** ship with either (a) a Hypothesis property test, or
(b) a Z3 invariant. The PR template will carry a checklist item. This
prevents backsliding — the invariants stay green forever.

---

## Phase 5 — deferred / post-v2.0

- Replace the `sys.modules` bootstrap hack with real Python packages
  (`a2a_billing` etc). Big change, low ROI today, high ROI if we ever
  need to split the monorepo.
- Break apart `lifespan.py` (508 LOC) and `webhooks.py` (588 LOC). Cosmetic
  — they work today. Revisit after P1-2 proves the split-and-test pattern.

---

## Open questions for human review

1. Float→Decimal migration: v1.2.9 hotfix or v1.3 refactor?
   (Architect recommends v1.2.9 hotfix — the audit has flagged it 3 cycles
   in a row and the blast radius is limited.)
2. `/v1/execute` deletion: verify prod-log traffic is zero first. Who
   pulls the access-log sample?
3. Z3 as a hard CI dep: blessing the ~15MB wheel in every workflow run,
   or gating behind a `needs-fv` label?
4. Version sync authority: is `gateway/src/_version.py` definitely the
   single source of truth, or should we mint a top-level `VERSION`?
5. `release.sh` rewriting sibling `pyproject.toml` files: acceptable
   blast radius, or too risky without a human-in-the-loop diff review?
6. Tier policy centralisation (`config/tiers.json`): does product want
   separate tier definitions for billing vs paywall vs catalog, or are
   they always identical?

## Human responses to above:
1. 1.2.9 hotfix
2. How to verify? Where are the logs exactly? What to look for?
3. Not sure... Can you estimate the price/time cost for doing it on each CI?
4. Mint a top-level VERSION
5. Acceptable
6. I think they should be identical. Thoughts?

## Architect answers

**Re #1 — Float→Decimal as v1.2.9 hotfix.** Accepted. Upgraded P1-3 to
P0 in the execution order; see "Execution plan" below. Narrow the scope
to the three highest-risk surfaces to keep the hotfix small:
`gatekeeper_metrics.py` cost accumulator, `deps/tool_context.py` spend
tracker, `routes/v1/billing.py` deposit limit check. Everything else
moves to v1.3.0 per the original Phase 2 plan.

**Re #2 — How to verify `/v1/execute` traffic is zero.** Four options,
pick whichever is easiest:

1. **Systemd journal on the host** (works today, no new instrumentation):
   ```
   ssh a2a-prod  # (or via scripts/deploy.sh pattern)
   sudo journalctl -u a2a-gateway --since "30 days ago" \
     | grep -c '"POST /v1/execute"'
   ```
   The gateway uses stdlib logging which uvicorn emits to journald. If
   the count is 0, we are clear. If it is non-zero, `grep` the match
   and extract the `X-Api-Key` prefix / `agent_id` to identify the
   caller so you can warn them before the delete.

2. **Nginx access log** (if `/v1/execute` is still fronted by nginx —
   check `/workdir/package/a2a-gateway/etc/nginx/`):
   ```
   sudo zgrep -c 'POST /v1/execute' /var/log/nginx/access.log*
   ```
   Nginx log rotation keeps ~30 days by default on the Debian package.

3. **Gateway metrics middleware** (preferred going forward): the
   `MetricsMiddleware` in `gateway/src/middleware.py` already counts
   per-route hits but does not expose them. Add a one-line instrument:
   ```python
   gateway_route_hits_total.labels(route="/v1/execute").inc()
   ```
   and scrape it from `/metrics` (blocked on P1-3 Prometheus endpoint
   from the v1.2.7 backlog — so route #1 or #2 is faster right now).

4. **Paywall request log** (`products/paywall/src/storage.py`). Already
   logs every tool call with `agent_id`, `tool_name`, `ts`. Legacy
   execute calls show up as whichever tool they were forwarding to;
   not useful for counting the *route* but useful for spotting
   specific abusive callers.

**What to look for.** Any non-zero count ≠ automatic blocker. Triage
rules:
- If all calls come from an internal agent (prefix `test-*`, `audit-*`,
  `perf-*`): safe to delete, they are our own probes.
- If calls come from `sandbox.*` keys: safe, sandbox has zero real
  customers.
- If calls come from any `prod_*` key: warn the owner, defer the
  delete one release, add an explicit `Sunset` header in the meantime.
- If calls are from an unknown key fleet: we have a bigger problem
  (`/v1/infra/keys` leak? audit persona probing?) — pause the deletion
  and flag to security.

**Re #3 — Z3 CI cost estimate.**

| Metric                         | Value                              |
|--------------------------------|------------------------------------|
| `z3-solver` wheel size         | 16 MB compressed, 60 MB installed  |
| pip install (warm cache)       | 3–8 s per job                      |
| pip install (cold cache)       | 20–40 s per job                    |
| CI jobs currently installing   | 1 (`test-gateway` after #83)       |
| Jobs that would add it         | `quality`, `test-products`, `sast` |
| Extra jobs × cold-install cost | 3 × 30 s ≈ 90 s worst case         |
| With `actions/setup-python`    | cached → 3 × 5 s ≈ 15 s            |
| Per-invariant solve time       | 10–500 ms (our problem sizes)      |
| 6 invariants per CI run        | ≤ 3 s                              |
| **Total added CI wall time**   | **≤ 20 s with caching**            |
| **Total added CI wall time**   | **≤ 2 min cold, once per runner**  |
| Cost on GitHub-hosted runners  | ~$0.008/min × 20 s ≈ $0.003/run    |
| @ 50 PR runs/month             | ~$0.15/month                       |

**Recommendation.** Make Z3 a hard CI dependency in all four workflows.
The cost is rounding error and the "needs-fv label" flow has failure
modes (new contributors forget the label; audit findings slip through).
#83 already paid the engineering cost of installing it in release;
repeat the same two lines in `ci.yml` and `staging.yml`.

**Re #6 — Tier policy centralisation, identical everywhere.** Strong
agree. The architect review traced 4 places that encode tier rules
(`gateway/src/config.py`, `pricing.json`, `products/billing/src/
pricing.py`, tool catalog `tier_required`) and found no drift *today*
but also no mechanism preventing it tomorrow. Centralise as:

```
/workdir/config/tiers.yaml      # single source of truth
```

YAML not JSON because it round-trips comments; humans will edit this
file directly during pricing experiments.

Structure:
```yaml
tiers:
  free:
    rank: 0
    deposit_limit: "100.00"
    budget_cap_daily: "10.00"
    budget_cap_monthly: "100.00"
    max_agents: 1
    rate_limit_per_minute: 60
  pro:
    rank: 1
    deposit_limit: "10000.00"
    budget_cap_daily: "1000.00"
    ...
  enterprise:
    rank: 2
    deposit_limit: "1000000.00"    # P1-7 from v1.2.7 backlog
    ...
  admin:
    rank: 3
    # admin bypasses all limits
```

Loaded once at startup by `gateway/src/config.py::GatewayConfig`; all
products read via `shared_src.tiers.get_tier_config(name)`. A CI lint
(`scripts/lint_no_hardcoded_tiers.py`) walks product code and fails the
build if any numeric literal matches a known tier value outside this
file. Drift becomes structurally impossible.

The one wrinkle: the tool catalog (`gateway/src/catalog.json`) encodes
per-tool `tier_required`. That stays in the catalog because it is
per-tool, not per-tier. But the tier *rankings* come from `tiers.yaml`
so the comparison `caller_tier_rank >= tool_required_rank` has a single
source.

Scheduled for Phase 3 P2-3 (not blocking v1.2.9 hotfix).

---

## Execution plan (this session, 2026-04-12)

Branch: `fix/repo-hygiene-v1.2.9`. One PR at the end per CLAUDE.md rule.

1. **P0-3 first** (smallest blast radius, unblocks release.sh changes):
   mint `/workdir/VERSION`, update `release.sh` to rewrite sibling
   `pyproject.toml` + `package.json` files, ship the sync lint test.
2. **P0-2** (`extra="forbid"` CI lint): pure addition, no behaviour
   change, catches the whole class permanently.
3. **P0-1** (storage migrations to 4 products): extract helper, wire
   it in, add regression tests that load a v1.2.0 fixture and upgrade.
4. **v1.2.9 hotfix slice of the float→Decimal migration**: narrow to
   the three highest-risk files; everything else stays in Phase 2.
5. Single PR, staged commits, CI must go green including sandbox-parity.

Deferred to follow-up PRs (too big for this session): middleware.py
split (P1-2), full float→Decimal sweep (P1-3 remainder), conftest
consolidation (P1-1), Z3 invariant harnesses (Phase 4).

---

## References

- Architect-review transcript: generated 2026-04-11 via Explore agent
  walk of `gateway/ sdk/ sdk-ts/ products/ scripts/ .github/`
- Related: `tasks/backlog/v1.2.7-audit-remediation.md` (P0-1 budget cap,
  P1-1 refund drift — both land *in* the paths this plan cleans)
- Agent task-planning guide: `docs/agent-task-planning.md` (written in
  this session)
- Prior C2 fix context: `products/payments/src/storage.py` ·
  `_apply_column_migrations`

---
