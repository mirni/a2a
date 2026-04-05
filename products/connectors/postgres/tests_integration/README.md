# PostgreSQL Connector — Live DB Integration Tests

These tests run the real `PostgresClient` and `TOOL_HANDLERS` against a
throwaway Postgres 16 container. Unlike `tests/` (which uses mocks), this
harness proves end-to-end behavior against a real DB.

Plan document: `tasks/backlog/postgres-connector-live-db-test.md`.

## Prerequisites

```bash
docker --version              # >= 20.10
docker compose version        # >= 2.0

# Install asyncpg into the venv (if not already):
HOME=/tmp /workdir/.venv/bin/python -m pip install "asyncpg>=0.30"
```

## Run the harness locally

```bash
cd /workdir/products/connectors/postgres/tests_integration

# 1. Start Postgres (seed.sql runs automatically on first container start)
docker compose up -d

# 2. Wait for readiness (usually <2s)
docker compose exec -T db pg_isready -U a2a_test -d a2a_connector_test

# 3. Run the tests — conftest.py auto-loads the default PG_* env vars
cd /workdir/products/connectors/postgres
HOME=/tmp /workdir/.venv/bin/python -m pytest tests_integration/ -v

# 4. Tear down (removes the tmpfs volume + all data)
cd tests_integration
docker compose down
```

## Run against an existing Postgres (skip Docker)

Point the harness at your own Postgres instance:

```bash
export PG_HOST=my-db-host PG_PORT=5432 \
       PG_DATABASE=mydb PG_USER=myuser PG_PASSWORD=xxx

cd /workdir/products/connectors/postgres
HOME=/tmp /workdir/.venv/bin/python -m pytest tests_integration/ -v
```

**WARNING:** `test_security_live.py` intentionally attempts injection
payloads and writes test rows. **Do not point it at a DB with real data.**
You must also seed the target DB with `seed.sql` first, or many tests
will fail on missing tables.

## Skipping

- Set `PG_INTEGRATION_SKIP=1` to skip all live-DB tests.
- If Postgres is not reachable at the configured host:port, the module
  is skipped (not failed) — safe to run in CI without a DB.
- If `asyncpg` is not installed, the module is skipped.

## Gateway E2E tests (optional)

`test_gateway_live.py` tests the full HTTP path through the gateway:

```bash
# Terminal 1: run the gateway against this test DB
cd /workdir
export PG_HOST=localhost PG_PORT=5433 PG_DATABASE=a2a_connector_test \
       PG_USER=a2a_test PG_PASSWORD=a2a_test_pwd_local_only PG_READ_ONLY=false
HOME=/tmp /workdir/.venv/bin/python -m uvicorn gateway.main:app --port 8000

# Terminal 2: run the E2E tests
export A2A_GATEWAY_URL=http://localhost:8000
export A2A_PRO_KEY=<a pro-tier API key registered on that gateway>
export A2A_FREE_KEY=<a free-tier API key registered on that gateway>

cd /workdir/products/connectors/postgres
HOME=/tmp /workdir/.venv/bin/python -m pytest tests_integration/test_gateway_live.py -v
```

If `A2A_GATEWAY_URL` is unset, the module is skipped.

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Postgres 16-alpine on port 5433, tmpfs volume |
| `seed.sql` | Schema + seed data (4 tables, 1 view, 10k-row `big_table`) |
| `conftest.py` | Pytest fixtures + skip logic + env-var defaults |
| `pytest.ini` | Standalone pytest config (overrides parent pyproject) |
| `test_client_live.py` | `PostgresClient` connection, pool, query, execute |
| `test_tools_live.py` | `TOOL_HANDLERS` via real client |
| `test_security_live.py` | Injection resistance, read-only enforcement, timeouts |
| `test_gateway_live.py` | E2E through `/v1/execute` (skipped unless gateway URL set) |

## Known issues

- **`LIMIT {max_rows}` template interpolation** (`src/client.py:99`): the
  max_rows value is concatenated into SQL text. Pydantic types it as
  `int` at the handler layer, which neutralizes string-injection. If
  `test_security_live.py::test_max_rows_cannot_inject_sql` fails, add
  explicit `int()` cast + bounds clamp in `client.py` before
  interpolation.
- **Read-only via `SET TRANSACTION READ ONLY`** is issued per-acquire on
  the pool. Verify this holds under concurrent writes.
