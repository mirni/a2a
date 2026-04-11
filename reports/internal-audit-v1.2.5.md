# Internal Audit — v1.2.5 (branch `fix/v1.2.4-audit-p1`)

**Date:** 2026-04-11
**Auditor:** Claude (internal review, pre-merge)
**Scope:** commits `main..fix/v1.2.4-audit-p1` (7 commits, 65 files,
+13,052 / -169 lines) covering v1.2.4 audit P0 remediation, P1 test
strategy upgrades, and Sprint-1 distribution channel work.

## Summary verdict

**GO — merge approved** after the HIGH finding in the first-pass
review (H1 — missing router-level admin guard on `/v1/infra/*`) was
remediated in-branch at commit `6ba2d5e`. The four MEDIUM findings
are worth follow-up but do not block release; they are tracked in
`tasks/backlog/v1.2.4-audit-p2.md` to be picked up after merge.

All 1681 gateway tests pass. CI pipeline is green on both parent
branches (P0 run `24277522538`, P1 run `24277538561`); the follow-up
run after the H1 fix is in progress at the time of writing.

## Findings by severity

### CRITICAL

None.

### HIGH — **RESOLVED in-branch**

**H1. Router-level admin guard on `/v1/infra/*` was promised but not
wired.** Commit `4b07086` added `list_api_keys`, `rotate_key`, and
existing database tools to `ADMIN_ONLY_TOOLS` and introduced the
`require_admin_tier` helper in `gateway/src/deps/auth.py:79`, but the
`/v1/infra` `APIRouter` at `gateway/src/routes/v1/infra.py:33` was
never given a router-level `dependencies=[Depends(require_admin_tier)]`
entry, leaving the "belt-and-braces" guarantee from the P0 plan
unmet. Any future route added under the infra prefix that forgot the
per-tool check would silently bypass the admin gate.

**Resolution** (`6ba2d5e`): split infra.py into three sub-routers
all mounted at `/v1/infra`, each with a clear security posture —

| Sub-router | Routes | Auth |
|---|---|---|
| `_legacy_router` | `POST /v1/infra/keys` → 410 Gone | None (deprecation banner reachable by any tier) |
| `_admin_router` | `GET /keys`, `POST /keys/revoke`, `POST /keys/rotate`, `GET /audit-log`, `GET /databases/backups`, `POST /databases/*/backup`, `POST /databases/*/restore`, `GET /databases/*/integrity` | router-level `require_admin_tier` dep |
| `router` (public) | webhooks CRUD, events publish/schema | per-tool enforcement (pro-accessible by design) |

The legacy 410 shim is included *first* in `app.py` so FastAPI
matches the exact path before the admin router sees it — the
deprecation banner wins the race for free-tier callers who hit the
old path. All 21 infra-admin-gate tests + 10 webhook pro-tier tests
pass after the split.

### MEDIUM

**M1. Budget cap bypass on legacy `/v1/execute` path.**
`gateway/src/routes/execute.py:507-520` performs the balance check
but does not consult `check_budget_cap` the way
`gateway/src/deps/tool_context.py:162` does on the REST routes. When
`A2A_LEGACY_EXECUTE=1` is set (staging/testing only), connector
tools dispatched through `/v1/execute` could exceed the configured
cap because the check is missing.

**Impact:** Low in production (legacy execute is disabled) but the
audit team's probe deliberately toggles this flag. Recommend adding
a budget-cap check alongside the balance check in the legacy flow,
or an explicit `raise 410` for cap-controlled tools.

**Test gap:** `gateway/tests/v1/test_budget_cap_enforcement.py` only
tests REST routes.

**Tracking:** `tasks/backlog/v1.2.4-audit-p2.md` — P2-M1.

**M2. Idempotency placeholder-row recovery after handler crash.**
`gateway/src/deps/idempotency.py:128-186` uses `status_code = 0` as
an in-flight marker. A replay after a handler crash
(between INSERT and UPDATE) matches the body_hash, sees
`status_code == 0`, and proceeds again — violating the idempotency
invariant if the original handler had partially completed (e.g.
debited the wallet but not yet recorded the response).

**Recommendation:** Use `status_code = -1` as the in-flight sentinel
and add a TTL of 30 s so stalled rows are reclaimable by a retry.
Cover with a test `test_idempotency_placeholder_timeout_allows_retry`.

**Tracking:** `tasks/backlog/v1.2.4-audit-p2.md` — P2-M2.

**M3. Admin deposit bypass is implicit.** In
`gateway/src/routes/v1/billing.py:164-175`, the admin tier bypasses
the cap check only because `config.deposit_limits.get("admin")`
returns `None`. This is subtle and fragile: a typo in the config
could silently expose enterprise-like behavior to all tiers.

**Recommendation:** Make the bypass explicit:

```python
if tc.agent_tier == ADMIN_TIER:
    return  # admin bypass, documented above
```

Plus a regression test `test_admin_scoped_key_bypasses_deposit_limits`.

**Tracking:** `tasks/backlog/v1.2.4-audit-p2.md` — P2-M3.

**M4. No cleanup task for expired idempotency rows.**
`gateway/src/deps/idempotency.py:56-68` defines an
`idx_idempotency_created` index but no periodic delete. Table grows
unbounded, a compliance/audit concern rather than a security bug.

**Recommendation:** Add a background coroutine (started from
`lifespan.py`) that runs
`DELETE FROM idempotency_cache WHERE created_at < NOW() - :ttl`
once per hour. TTL matches the existing 24h replay window.

**Tracking:** `tasks/backlog/v1.2.4-audit-p2.md` — P2-M4.

### LOW

**L1. Well-known routes are unmetered.**
`gateway/src/routes/well_known.py` serves six public endpoints with
no rate limit. Bodies are small and `llms-full.txt` only walks
`request.app.routes` at request time (cheap), but an attacker could
still hammer them. Cloudflare rate limiting in front of the gateway
should handle DoS, but the application has no backstop.

**Recommendation:** Document the assumption that all unauthenticated
paths are rate-limited at the edge, or add a lightweight per-IP
limiter in `PublicRateLimitMiddleware` for `/.well-known/*` paths.

**L2. Health SLO exists only in tests, not in runtime.**
`gateway/tests/perf/test_health_p50_slo.py` enforces p50 < 50 ms and
blocks merge on regression, but there's no runtime alarm. If latency
regresses post-merge, we find out from the next test run, not from a
monitor.

**Recommendation:** Emit a `gateway_health_latency_seconds` histogram
and hook a Prometheus alert when `p99 > 1s`.

**L3. `time.time()` for cap windows is NTP-sensitive.**
`gateway/src/deps/tool_context.py:234-262` uses wall-clock seconds
for the daily/monthly window boundary. A backward NTP step of 1h
would reset the daily window early.

**Recommendation:** Acknowledge the assumption in a code comment
(system clock is NTP-disciplined), or switch to DB-managed windows
(`CURRENT_TIMESTAMP` in SQL) for the boundary calculation.

### INFO / strengths observed

- **RFC compliance:** 410 and 402 responses use RFC 9457 problem+json;
  Deprecation/Sunset/Link headers follow RFC 8594 (`execute.py:45-66`).
- **Atomic idempotency reserve** via `INSERT OR IGNORE` on the
  `(idempotency_key)` primary key removes the need for a
  distributed lock in the hot path.
- **Pydantic models** consistently use `extra="forbid"` across all
  new request bodies (verified in `infra.py`, `billing.py`,
  `payments.py`).
- **Multi-tenant fixtures** provision 5 agents across 4 tiers in
  `gateway/tests/v1/test_infra_admin_gate.py:26-65` so cross-tenant
  contamination is caught by construction.
- **Route enumeration contract** (`test_route_enumeration.py`) walks
  `app.routes` at test time and fails the build if a new route
  lands without either a test file or `include_in_schema=False`.
- **OpenAPI diff gate** (`test_openapi_schema_diff.py`,
  `scripts/dump_openapi.py`, `scripts/ci/diff_openapi.py`) pins the
  public schema at v1.2.4 and flags removals or type changes.
- **Sandbox parity CI** (`.github/workflows/ci.yml` job
  `sandbox-parity`) runs the audit personas' exact probes against
  the live sandbox environment; currently `continue-on-error: true`
  until the 3 sandbox audit keys are provisioned (runbook:
  `tasks/backlog/sandbox-audit-keys.md`).
- **SDK Timestamp validator** accepts both ISO-8601 strings and
  POSIX floats, letting v1.2.4 clients talk to v1.2.5 servers (and
  vice-versa) without the crash that the external auditor hit in
  v1.2.4.
- **Admin audit log + anomaly detector** record every admin tool
  operation and auth failure — good forensic coverage.
- **Paywall coverage** restored to 99% after commit `65cdd16` added
  `test_get_all_keys_admin_fleet` and `test_get_all_keys_empty`
  against both `products/paywall/src/storage.py` and
  `products/paywall/src/keys.py`.

## Distribution work (Sprint 1 from
`tasks/backlog/distribution-execution-queue.md`)

**A3 — `/.well-known/*` discovery endpoints.** Six routes added in
`gateway/src/routes/well_known.py`, all `include_in_schema=False`,
all bypassing auth (expected for discovery). 9 regression tests in
`gateway/tests/test_well_known.py`. Verified that `llms-full.txt`
does not leak sensitive information — it only exposes path + HTTP
method, which the public OpenAPI spec already reveals.

**A7 — IDE integration docs.** Five editor-specific MCP install
recipes plus an index at `docs/integrations/`:
- `claude-desktop.md` — macOS/Windows/Linux config paths
- `cursor.md` — stdio + HTTP transport options
- `claude-code.md` — `claude mcp add` one-liner + manual
- `windsurf.md` — `~/.codeium/windsurf/mcp_config.json`
- `zed.md` — `context_servers` settings
All point at the published `@greenhelix/mcp-server` package and the
same API key format `a2a_{tier}_{hex}`.

**A22 — ClawMart channel.** Added to
`tasks/backlog/distribution-execution-queue.md` under a new
Sprint 4 section with a `**Publishing gate:** HOLD` marker so no
actual publication happens before this audit's MEDIUM items clear.
Referenced `docs/clawmart_how_to.txt` for the SKILL.md / PERSONA.md
/ SOUL.md / MEMORY.md creator artifacts the marketplace expects.

## Follow-up queue

Create / update `tasks/backlog/v1.2.4-audit-p2.md` with the MEDIUM
and LOW items above. Priority order (hardest-edged first):

1. **P2-M2 idempotency placeholder TTL** (correctness)
2. **P2-M3 explicit admin bypass on deposit limits** (clarity + test)
3. **P2-M1 budget cap in legacy execute path** (correctness)
4. **P2-M4 idempotency row cleanup** (hygiene)
5. **P2-L2 runtime health-latency histogram + alert** (observability)
6. **P2-L1 well-known rate limit documentation/backstop** (hygiene)
7. **P2-L3 NTP-safe cap window** (defense in depth)

All items are small (< 1 day each) and independent — can be batched
into a single `fix/v1.2.5-audit-p2` branch after the current release.

## CI status at audit time

- **P0 PR #84** — run `24277522538` ✅ all green (1 staging deploy in
  progress is the only non-complete entry).
- **P1 PR #85** — run `24277538561` ✅ all green on the pre-H1 state;
  a new run triggered by the H1 fix (`6ba2d5e`) and distribution
  commit (`027e295`) is in flight.
- **Local full gateway suite** — 1681 passed (428 s) after the H1
  split. Zero failures, zero warnings beyond the pre-existing
  `pytest.mark.asyncio on sync function` advisory in `test_billing.py`.

## Conclusion

The v1.2.5 release candidate addresses all seven P0 findings from
the external v1.2.4 audit with proportionate fixes and regression
coverage, plus the cross-cutting test strategy upgrades (T-1 through
T-5) that the external auditors asked for. The in-branch fix for H1
converted a "plan claimed, code missing" gap into a clean three-way
router split that makes the admin surface impossible to accidentally
unguard. The remaining MEDIUM items are genuine improvements but
not blockers — ship, then address them in p2.

**Recommendation:** Merge PR #84 once its staging deploy completes,
then merge PR #85 (which daisy-chains off #84). Tag `v1.2.5` after
both merges land. Do not publish to ClawMart, PyPI, or npm until
after the internal sandbox-parity CI job has run green against live
sandbox credentials (prerequisite: human follows
`tasks/backlog/sandbox-audit-keys.md`).
