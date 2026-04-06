# PostgreSQL Connector — Live Database Test Plan

**Priority:** BLOCKER (part of go-live preflight, Phase 4 CONN-6)
**Status:** backlog
**Effort:** 3-4h (mostly automated once harness is built)

## Context

The PostgreSQL MCP connector (`products/connectors/postgres/`) has
**never been tested against a real Postgres instance**. All existing
tests (`test_tools.py`, `test_client.py`, `test_models.py`) use
`AsyncMock` / `MagicMock` — so we have no evidence that:

- `asyncpg` connects and pools correctly
- SQL parameterization (`$1, $2, ...`) actually prevents injection
  when a real DB parses it
- `SET TRANSACTION READ ONLY` blocks writes at the DB layer (not just
  via the Python-side `read_only` flag)
- `information_schema` queries work on modern PG versions (14, 15, 16)
- `EXPLAIN ANALYZE` produces parseable output
- Connection-pool exhaustion + reconnection behavior is correct
- Statement timeouts actually fire on slow queries
- `LIMIT {max_rows}` injection via SQL template string (line 99 of
  `client.py`) is safe — we're concatenating `max_rows` into SQL text

The connector is also exposed end-to-end via the gateway
(`/v1/execute` with tools `pg_query`, `pg_execute`, `pg_list_tables`,
`pg_describe_table`, `pg_explain_query`, `pg_list_schemas`) with the
`validate_pg_execute_sql()` gate in `gateway/src/sql_validator.py`.
We must test BOTH layers: direct client calls AND through-the-gateway
calls.

## Goals

1. **Prove the connector works at all** against a real DB.
2. **Prove read-only mode** is enforced (Python + DB layer both).
3. **Prove SQL injection resistance** via parameterization.
4. **Prove the SQL validator gate** in the gateway catches bad SQL.
5. **Prove resource limits** (timeout, max_rows, pool size) hold.
6. **Produce a reusable harness** that future devs can run locally in
   <60s to validate connector changes.

## Test harness architecture

```
products/connectors/postgres/tests_integration/
├── docker-compose.yml          # Postgres 16 in a throwaway container
├── seed.sql                    # Schema + seed data (~100 rows)
├── conftest.py                 # pytest fixtures: start/stop PG, env vars
├── test_client_live.py         # Direct PostgresClient tests
├── test_tools_live.py          # TOOL_HANDLERS tests with real client
├── test_security_live.py       # SQL injection, read-only bypass attempts
├── test_gateway_live.py        # Full E2E through /v1/execute
└── README.md                   # How to run locally
```

### `docker-compose.yml`
- Postgres 16-alpine
- Port 5433 (avoid colliding with local dev instance)
- Throwaway volume (`tmpfs` for speed)
- Healthcheck via `pg_isready`

### `seed.sql`
- Schema: `public` + `test_schema`
- Tables:
  - `users (id SERIAL PK, email TEXT UNIQUE, name TEXT, created_at TIMESTAMPTZ DEFAULT NOW())`
  - `orders (id SERIAL PK, user_id INT REFERENCES users, amount NUMERIC(10,2), status TEXT)`
  - `products (id SERIAL PK, sku TEXT UNIQUE, name TEXT, price NUMERIC(10,2))`
  - `test_schema.audit_log (id BIGSERIAL PK, event TEXT, payload JSONB, ts TIMESTAMPTZ)`
- 50 users, 200 orders, 30 products, 100 audit_log entries
- One large table `big_table` with 10k rows for `max_rows` + timeout tests
- One view `orders_summary` for view-vs-table distinction testing

## Test cases (by category)

### Connection + pool (test_client_live.py)
- `test_connect_success` — pool initializes, logs connection
- `test_connect_bad_host` — raises within 5s (timeout)
- `test_connect_bad_credentials` — raises `InvalidAuthorizationSpecificationError`
- `test_pool_exhaustion_recovers` — acquire 10 connections, release, reuse
- `test_close_then_reconnect` — close → query raises → connect → query succeeds

### `query` tool
- `test_query_simple_select` — returns list of dicts
- `test_query_with_params` — `SELECT * FROM users WHERE email = $1`
- `test_query_max_rows_enforced` — request 50 from `big_table`, get 50
- `test_query_max_rows_cap` — request 99999, get capped at 10000
- `test_query_timeout_fires` — `SELECT pg_sleep(5)` with `timeout=1.0` raises
- `test_query_empty_result` — returns `[]` for no matches
- `test_query_types_serialize` — TIMESTAMPTZ, NUMERIC, JSONB, UUID round-trip
- `test_query_null_values` — NULL columns return Python `None`

### `execute` tool
- `test_execute_blocked_in_readonly_mode` — raises `PermissionError`
- `test_execute_insert_with_params` — INSERT ... RETURNING id, verify row exists
- `test_execute_update_with_params` — UPDATE returns `"UPDATE 1"`
- `test_execute_delete_with_params` — DELETE returns `"DELETE 1"`
- `test_execute_affects_correct_row_only` — parameterized WHERE restricts scope

### `list_tables` tool
- `test_list_tables_public_schema` — returns all 4 tables
- `test_list_tables_custom_schema` — returns `audit_log` from `test_schema`
- `test_list_tables_empty_schema` — returns `[]`
- `test_list_tables_includes_views` — `orders_summary` appears with `table_type=VIEW`

### `describe_table` tool
- `test_describe_table_returns_columns` — all columns present with types
- `test_describe_table_nullable_flags` — `is_nullable` correct
- `test_describe_table_defaults` — `column_default` includes `nextval(...)` for serial
- `test_describe_nonexistent_table` — returns `[]`

### `explain_query` tool
- `test_explain_basic_query` — returns string with "Seq Scan" or "Index Scan"
- `test_explain_analyze_executes` — `analyze=True` produces timing info
- `test_explain_analyze_readonly_safe` — EXPLAIN ANALYZE on SELECT OK in read-only mode

### `list_schemas` tool
- `test_list_schemas_excludes_system` — `pg_catalog`, `information_schema`
  not present
- `test_list_schemas_includes_custom` — `test_schema` appears
- `test_list_schemas_includes_public` — `public` appears

### SQL injection + read-only bypass (test_security_live.py)
- `test_injection_in_email_param_blocked` — `email='"; DROP TABLE users; --"'`
  used as param is harmless (table still exists)
- `test_injection_in_email_fails_in_sql_text` — same payload concatenated
  into SQL TEXT would raise (document that tools only allow params)
- `test_readonly_blocks_insert_at_db_layer` — even if Python `read_only=False`
  check was bypassed, the `SET TRANSACTION READ ONLY` sent per-acquire
  would make INSERTs fail with "cannot execute INSERT in a read-only
  transaction"
- `test_max_rows_limit_literal_injection` — can a maliciously-crafted
  query exploit the `LIMIT {max_rows}` text concatenation on line 99
  of `client.py`? Attempt: `max_rows=-1; DROP TABLE users --`. Expected:
  `max_rows` should be typed as `int`, so string injection is blocked
  at the Python level. **If it's not, this is a finding.**
- `test_timeout_prevents_runaway_query` — pg_sleep(30) with timeout=1.0
  raises; DB connection is returned to pool (not leaked)
- `test_multiple_statements_blocked_by_asyncpg` — asyncpg rejects
  `SELECT 1; SELECT 2` at the protocol level

### SQL validator gate (test_gateway_live.py)
Test the full stack: HTTP request → gateway validator → MCP proxy →
asyncpg → real PG. Requires the gateway to be running against this
test DB.

- `test_gateway_pg_query_success` — returns dict rows
- `test_gateway_pg_execute_select_blocked` — validator rejects SELECT
  via `pg_execute` (wrong tool)
- `test_gateway_pg_execute_drop_blocked` — validator rejects `DROP TABLE`
- `test_gateway_pg_execute_multi_statement_blocked` — `INSERT ...; DELETE ...`
  rejected
- `test_gateway_pg_execute_requires_params` — `INSERT INTO users VALUES ('x')`
  without `params` array rejected (forces parameterization)
- `test_gateway_pg_list_tables_free_tier_requires_pro` — 403 insufficient_tier
- `test_gateway_pg_list_tables_pro_tier_works` — pro-tier key → 200
- `test_gateway_pg_query_charges_wallet` — balance decreases by 0.005 credits

## Human operator setup instructions

### Prerequisites
```bash
# Docker + docker-compose already installed
docker --version     # >= 20.10
docker compose version  # >= 2.0
# Python venv with asyncpg
cd /workdir
HOME=/tmp /workdir/.venv/bin/python -m pip install "asyncpg>=0.29,<1.0" pytest-asyncio
```

### One-time: decide PG_* values for local testing
No secrets needed — the Docker Postgres is ephemeral. Defaults:
```
PG_HOST=localhost
PG_PORT=5433
PG_DATABASE=a2a_connector_test
PG_USER=a2a_test
PG_PASSWORD=a2a_test_pwd_local_only
PG_READ_ONLY=true  # flip to false for write tests (tests manage this)
```

### Run the harness
```bash
cd products/connectors/postgres/tests_integration
docker compose up -d                     # start Postgres
docker compose exec -T db pg_isready -U a2a_test  # wait for readiness

# Run tests (harness auto-loads PG_* env vars from .env.test)
HOME=/tmp /workdir/.venv/bin/python -m pytest . -q

# Tear down
docker compose down -v                   # -v removes the tmpfs volume
```

### Optional: test the gateway E2E
```bash
# In terminal 1: run gateway with the test DB
cd /workdir
export PG_HOST=localhost PG_PORT=5433 \
  PG_DATABASE=a2a_connector_test PG_USER=a2a_test \
  PG_PASSWORD=a2a_test_pwd_local_only PG_READ_ONLY=false
HOME=/tmp /workdir/.venv/bin/python -m uvicorn gateway.main:app --port 8000

# In terminal 2: run E2E tests against localhost:8000
export A2A_GATEWAY_URL=http://localhost:8000
HOME=/tmp /workdir/.venv/bin/python -m pytest tests_integration/test_gateway_live.py -q
```

### Optional: test against an existing Postgres instance
Skip the Docker harness and export your own `PG_*` vars. The test
suite detects an existing DB via env vars and skips the Docker
startup. **Warning:** `test_security_live.py` intentionally tries to
write + drop things. **Do not run against a DB with real data.**

## CI integration (post-launch, non-blocking)

Add a GitHub Actions job `postgres-connector-integration`:
```yaml
postgres-integration:
  runs-on: ubuntu-latest
  services:
    postgres:
      image: postgres:16-alpine
      env:
        POSTGRES_DB: a2a_connector_test
        POSTGRES_USER: a2a_test
        POSTGRES_PASSWORD: a2a_test_pwd_local_only
      ports: ["5433:5432"]
      options: --health-cmd pg_isready --health-interval 2s --health-timeout 3s --health-retries 10
  steps:
    - uses: actions/checkout@v4
    - run: python -m pip install -e ".[dev]" asyncpg
    - run: psql -h localhost -p 5433 -U a2a_test -d a2a_connector_test -f products/connectors/postgres/tests_integration/seed.sql
      env: {PGPASSWORD: a2a_test_pwd_local_only}
    - run: python -m pytest products/connectors/postgres/tests_integration/ -q
      env: {PG_HOST: localhost, PG_PORT: "5433", PG_DATABASE: a2a_connector_test,
            PG_USER: a2a_test, PG_PASSWORD: a2a_test_pwd_local_only, PG_READ_ONLY: "false"}
```

## Success criteria

- [ ] All test_client_live.py tests green
- [ ] All test_tools_live.py tests green
- [ ] All test_security_live.py tests green — including the `LIMIT {max_rows}`
  injection test (if it reveals a vulnerability, fix the client to cast
  `max_rows` to int and clamp before interpolation)
- [ ] All test_gateway_live.py tests green
- [ ] Harness runs end-to-end locally in <60s (docker up → tests pass → down)
- [ ] CI job added and green
- [ ] README explains how to run + how to debug failures
- [ ] Known issues documented in `products/connectors/postgres/README.md`

## Risks / likely findings

1. **`LIMIT {max_rows}` template injection** (client.py:99) — if
   `max_rows` isn't type-guarded, this is a SQLi vector. Expected
   finding: add `max_rows = min(int(max_rows), 10000)` before
   interpolation.
2. **Read-only `SET TRANSACTION READ ONLY`** may not apply to INSERT
   via a new pool acquire (transactions are per-connection). Expected
   finding: either set it at pool-init level or at every statement.
3. **Pool exhaustion** behavior undefined — default asyncpg pool is
   10 connections; what happens under load?
4. **Timezone handling** — TIMESTAMPTZ round-trip may surprise.

## Completed

### 2026-04-05 — Harness scaffolded (not yet executed)

The test harness is implemented at `products/connectors/postgres/tests_integration/`:

| File | Lines | Purpose |
|------|-------|---------|
| `docker-compose.yml` | ~35 | Postgres 16-alpine, port 5433, tmpfs volume, fsync off |
| `seed.sql` | ~100 | 4 tables + 1 view + `big_table` (10k rows) + `test_schema.audit_log` |
| `conftest.py` | ~130 | Fixtures (`rw_client`, `ro_client`, `make_config`, `clean_users_slate`) + `collect_ignore_glob` skip logic |
| `pytest.ini` | ~8 | Standalone config (overrides connector's parent `pyproject.toml`) |
| `test_client_live.py` | 27 tests | Connection, pool, query, execute, schema introspection |
| `test_tools_live.py` | 14 tests | MCP `TOOL_HANDLERS` via real client |
| `test_security_live.py` | 10 tests | Injection neutralization, read-only enforcement, multi-stmt block, timeout safety |
| `test_gateway_live.py` | 8 tests | E2E via `/v1/execute` (skipped unless `A2A_GATEWAY_URL` set) |
| `README.md` | — | Run instructions (Docker + existing-DB modes, gateway E2E setup) |

**Total: 59 tests across 4 modules.**

Verification performed without a running Postgres:
- All 4 test modules import cleanly (validated via direct `importlib` load)
- `ruff check` and `ruff format --check` pass
- `pytest --collect-only` correctly skips the whole suite when Postgres is
  unreachable or `asyncpg` is missing (via `collect_ignore_glob`)
- When `A2A_GATEWAY_URL` is unset, `test_gateway_live.py` is skipped at
  module level; the other 3 modules run independently

**Next step (requires human or Docker-enabled environment):**
1. `cd products/connectors/postgres/tests_integration && docker compose up -d`
2. `cd .. && HOME=/tmp /workdir/.venv/bin/python -m pytest tests_integration/ -v`
3. Record results; address any failures (especially
   `test_max_rows_cannot_inject_sql` — if it fails, patch `client.py:99`
   per the "Risks / likely findings" section).
4. Add GitHub Actions CI job per the YAML template above.

### 2026-04-06 — Defense-in-depth fix + CI job added

1. **`LIMIT {max_rows}` defense-in-depth fix** (client.py line 120):
   - Added `max_rows = min(int(max_rows), 10_000)` before SQL interpolation
   - Cast to int rejects string injection at the Python layer (before it reaches Postgres)
   - Clamp to 10,000 matches pydantic model constraint (`Field(..., le=10000)`)
   - 3 new unit tests in `tests/test_client.py::TestMaxRowsDefenseInDepth`
   - TDD: tests written first (RED), fix applied (GREEN), full suite verified (51 tests pass)

2. **GitHub Actions CI job** added to `.github/workflows/ci.yml`:
   - Job `postgres-integration` with `continue-on-error: true` (non-blocking)
   - Uses GitHub Actions service container: `postgres:16-alpine` on port 5433
   - Seeds DB with `seed.sql`, runs `tests_integration/` via pytest
   - PYTHONPATH configured for `shared` module imports

3. **Verification**:
   - Ruff lint: all checks passed (14 files)
   - Ruff format: all files formatted
   - pytest collection: skips gracefully when Postgres unreachable
   - Gateway test suite: 1403 tests pass (no regressions)

Still requires human/Docker-enabled environment:
- Actual execution of all 51 integration tests against a live Postgres
- Recording pass/fail results for each test case
- Documenting any additional findings in `products/connectors/postgres/README.md`
