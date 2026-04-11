# v1.2.4 Audit P0 Remediation — Response

Date: 2026-04-11
Branch: `fix/v1.2.4-audit-p0`
Audit source: `reports/external/v1.2.4/multi-persona-audit-v1.2.4-2026-04-11.md`
Verdict before this PR: **NO-GO, 5.0/10** (unchanged for 4 consecutive releases)

This document maps every P0 finding from the v1.2.4 audit to its
remediation in this branch. All fixes land in a single PR per user
direction.

---

## P0-1 — `/v1/infra/*` admin gate & self-service key migration

**Finding.** FREE/PRO/ENT callers could reach `GET /v1/infra/keys`,
`POST /v1/infra/keys`, `POST /v1/infra/keys/rotate`, and related
infrastructure tools, exposing their own key metadata and allowing
self-service key fleet expansion through an operator-only surface.

**Fix.**
- `gateway/src/authorization.py`: expanded `ADMIN_ONLY_TOOLS` to
  include `list_api_keys`, `create_api_key`, `rotate_api_key`,
  `list_db_keys`, `list_tls_keys`, `backup_database`, `restore_database`,
  `check_db_integrity`, `list_backups`.
- `gateway/src/deps/auth.py`: new `require_admin_tier(request)` helper
  that raises 403 `forbidden_admin_only` (RFC 9457) on any non-admin
  caller.
- `gateway/src/routes/v1/infra.py`: router-wide
  `Depends(require_admin_tier)` belt-and-braces. Every route under
  `/v1/infra/*` is now admin-only even if a future developer forgets
  to mark the tool.
- `gateway/src/routes/v1/billing.py`: new self-service
  `POST /v1/billing/keys` / `GET /v1/billing/keys` routes, non-admin
  but scoped to caller's own `agent_id`.
- `POST /v1/infra/keys` returns **410 Gone** with RFC 8594
  `Deprecation` / `Sunset` / `Link rel=successor-version` headers
  pointing at `/v1/billing/keys`.

**Regression tests.**
- `gateway/tests/v1/test_infra_admin_gate.py` — new. Parametric
  multi-tenant fixture (free / pro / admin × 2 keys each). Asserts
  every route under `/v1/infra/*` returns 403 for non-admin and 200
  for admin. Asserts `/v1/billing/keys` returns only the caller's
  own keys. Cross-tenant probe blocked with 403. Deprecation
  headers verified on `POST /v1/infra/keys`.

## P0-2 — `/v1/execute` 410 Gone correctness

**Finding.** Legacy `/v1/execute` returned **422 Unprocessable
Entity** instead of 410 when callers passed a body that didn't
match the old Pydantic model. Audit personas saw "deprecated" next
to "schema error" and flagged it as route drift.

**Fix.**
- `gateway/src/routes/execute.py`: new `_legacy_execute_gone()`
  helper that returns a fixed 410 with `endpoint_removed` code plus
  RFC 8594 `Deprecation` / `Sunset` / `Link` headers.
- `_execute_impl()` now parses the body just enough to extract
  `tool_name`, then dispatches on route-hit first: when not in legacy
  mode and the tool isn't a connector, return 410 **regardless** of
  body shape (valid, garbage, missing, array — all 410).
- Connector tools (Stripe/GitHub/Postgres MCP) still route through
  `/v1/execute` because they have no dedicated REST path.

**Regression tests.**
- `gateway/tests/v1/test_execute_deprecation.py` — new. Ten tests
  covering valid legacy body, missing `tool` field, extra fields,
  garbage body, empty body, array body, unknown tool, RFC 9457
  shape, `Sunset` + `Link` headers, unauthenticated.

## P0-3 — SDK `created_at` type alignment

**Finding.** `RegisterAgentResponse.created_at` was typed as `float`
in the SDK, but the server started returning ISO-8601 strings
somewhere between v1.2.2 and v1.2.4. SDK callers hit
`pydantic.ValidationError` on every register call.

**Fix.**
- `sdk/src/a2a_client/models.py`: new `_parse_timestamp()`
  `BeforeValidator` accepting `datetime`, `int`/`float`, numeric
  strings, ISO-8601 strings (including the `Z` suffix), and `None`.
  Emitted as `datetime`.
- Defined `Timestamp = Annotated[datetime, BeforeValidator(...)]`
  and `OptionalTimestamp` for nullable fields.
- Replaced all `created_at: float` with `Timestamp` across
  `RegisterAgentResponse`, `GetAgentIdentityResponse` (nullable),
  and four other response models.

**Regression tests.**
- `sdk/tests/test_register_agent_contract.py` — new. Nine tests
  across three classes: ISO-8601 string acceptance, float/int
  acceptance, roundtrip invariants. Hypothesis-style property
  tests covering random timestamp roundtrips.

## P0-4 — Idempotency body-hash validation

**Finding.** `POST /v1/payments/intents` with replayed
`Idempotency-Key` but **different body** silently created a
second intent. The billing-layer idempotency worked only on the
key itself, not the request body.

**Fix.**
- `gateway/src/deps/idempotency.py` — new module. Stores
  `(agent_id, key, body_hash, status_code, response_json, created_at)`
  in an `idempotency_cache` table in the paywall DB.
- `_canonical_body_hash()` uses sort-keyed separators-tight JSON
  plus SHA-256, so structurally equivalent dicts always hash the same.
- `check_idempotency()` uses `INSERT OR IGNORE` on the composite
  primary key `(agent_id, key)` to atomically reserve-or-replay.
  Race-safe by construction: exactly one concurrent caller wins the
  insert; the rest read the winner's row.
- Returns `None` for clean path, a cached `JSONResponse` for same-body
  replay, or 409 `idempotency_key_reused` (RFC 9457) for body-hash
  collision.
- `record_idempotent_response()` finalises the placeholder row after
  the mutation succeeds.
- `gateway/src/routes/v1/payments.py`: `create_intent` now calls
  `check_idempotency` before the mutation and
  `record_idempotent_response` after.

**Regression tests.**
- `gateway/tests/v1/test_idempotency_collision.py` — new. Five
  tests: replay-same-body returns same id; replay-different-amount
  returns 409; replay-different-description returns 409; no-key
  produces distinct ids; **20-way parallel race** asserts exactly
  one succeeds and the other 19 return 409.

## P0-5 — Budget cap enforcement at the request path

**Finding.** `set_budget_cap` and `get_budget_status` reported
`cap_exceeded=true` but `POST /v1/payments/intents` still
succeeded on the next call. No middleware gate ever consulted
`budget_caps`.

**Fix.**
- `gateway/src/deps/tool_context.py`: added section 6b
  `_check_budget_caps()` after the balance check. For non-admin
  callers, when `cost > 0` **or** the request body carries a
  non-zero `amount` (to catch percentage-priced tools like
  `create_intent` where the gateway cost is 0 but the business
  amount is positive), the dep:
  1. Reads the `budget_caps` row (atomic-unit columns, scale 1e8).
  2. Calls `ctx.tracker.storage.sum_cost_since(agent_id, window_start)`
     for daily and monthly windows.
  3. Returns 402 `budget_exceeded` (RFC 9457) when
     `spend + pending_cost > cap`.
  4. Admin tier bypasses entirely.

**Regression tests.**
- `gateway/tests/v1/test_budget_cap_enforcement.py` — new. Five
  tests: under-cap succeeds; daily-cap exceeded returns 402;
  wallet not debited on 402; no cap configured still works;
  admin bypasses cap.

## P0-6 — Enterprise tier deposit limits

**Finding.** `GatewayConfig.deposit_limits` had entries for
`free` / `starter` / `pro` but no `enterprise` key. Enterprise
callers depositing any amount bypassed the check entirely
because `.get("enterprise")` returned `None`.

**Fix.**
- `gateway/src/config.py`: added explicit
  `"enterprise": 10_000_000` entry. **Policy placeholder** — the
  exact ceiling is a product decision and is flagged in the PR
  description for human confirmation before merge. Previous
  value (`1_000_000_000`) coincidentally equalled the Pydantic
  hard cap, making the tier check a no-op.

**Regression tests.**
- `gateway/tests/test_deposit_limits.py` — extended. Added
  enterprise within-limit, enterprise over-limit (403), and
  admin-bypass tests.

## P0-7 — `/v1/health` latency SLO

**Finding.** External audit measured p50=5.2s on sandbox, a ~25×
regression vs the ~200ms expected. Root cause unknown without
local repro against the live deploy.

**Fix.**
- `gateway/src/routes/health.py`: parallelised the 10-database
  `SELECT 1` probe via `asyncio.gather()`. Previously serial,
  which on a slow-I/O deploy compounds to ~10× the single-probe
  RTT. No semantic change — same status shape, same 503 on any
  DB down.
- `perf/p50_profile.py` — new triage script reporting p50/p95/p99
  plus cold/warm split against any URL. Used for local profiling.
- `gateway/tests/perf/test_health_p50_slo.py` — new SLO gate
  marked `@pytest.mark.slo`. 200 sequential health calls against
  the in-process ASGI client; asserts p50 < 50ms and p99 < 250ms.
  Catches any future regression that puts per-request work on the
  hot path.

---

## Verification

```bash
HOME=/tmp python -m pytest gateway/tests/ -q
# → 1663 passed

HOME=/tmp PYTHONPATH=src python -m pytest sdk/tests/ -q
# → 80 passed

HOME=/tmp python -m pytest products/billing/tests/ -q     # 223 passed
HOME=/tmp python -m pytest products/payments/tests/ -q    # 252 passed
HOME=/tmp python -m pytest products/paywall/tests/ -q     # 154 passed
```

All module test suites green. No regressions.

## Items flagged for human review

1. **Enterprise deposit cap (P0-6)** — currently set to 10,000,000
   credits. Previous value was 1,000,000,000 (coincidentally equal
   to the Pydantic hard cap). Confirm the policy value before merge.
2. **`/v1/billing/keys` dashboard wiring** — new self-service route
   must be reachable from the dashboard before `POST /v1/infra/keys`
   Sunset date expires.
3. **Sandbox SLO threshold** — the audit wanted p50 < 300ms on
   sandbox; the local gate is tighter (p50 < 50ms). The sandbox
   parity CI job (`tests/sandbox/`) is tracked as a follow-up so
   that we can add real-deploy assertions without blocking this PR
   on secret provisioning.

## Follow-ups

P1/P2 items and the sandbox-parity CI job are tracked in
`tasks/backlog/v1.2.4-audit-p1.md` for the next release cycle.
