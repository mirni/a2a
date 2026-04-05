#!/usr/bin/env bash
# =============================================================================
# PostgreSQL connector — live-DB integration test runner
# =============================================================================
# Runs the products/connectors/postgres/tests_integration/ suite against a
# real Postgres instance. Designed to be called from:
#   - CI (GH Actions with postgres service container; just run this)
#   - Local dev (with --docker flag to start/stop docker compose)
#   - An existing DB (export PG_* env vars, then run)
#
# Usage:
#   scripts/run_pg_connector_tests.sh [OPTIONS]
#
# Options:
#   --docker              Start docker-compose Postgres before tests, tear
#                         down after (requires docker + docker compose)
#   --no-teardown         When --docker is set, leave the container running
#                         after tests (useful for debugging)
#   --seed                Apply seed.sql via psql before running tests.
#                         CI doesn't need this (docker image runs initdb
#                         scripts automatically); only useful for existing
#                         DBs that have not been seeded yet.
#   -h, --help            Show help
#
# Environment variables (all have sensible defaults for docker-compose):
#   PG_HOST       (default: localhost)
#   PG_PORT       (default: 5433)
#   PG_DATABASE   (default: a2a_connector_test)
#   PG_USER       (default: a2a_test)
#   PG_PASSWORD   (default: a2a_test_pwd_local_only)
#   PG_READ_ONLY  (default: false — tests manage this per-test)
#   PYTEST_ARGS   (default: -q)     extra args appended to the pytest call
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS_DIR="$REPO_ROOT/products/connectors/postgres/tests_integration"

USE_DOCKER=false
TEARDOWN=true
RUN_SEED=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --docker)       USE_DOCKER=true; shift ;;
        --no-teardown)  TEARDOWN=false; shift ;;
        --seed)         RUN_SEED=true; shift ;;
        -h|--help)
            sed -n '/^# Usage:/,/^# ====/p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)              echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

export PG_HOST="${PG_HOST:-localhost}"
export PG_PORT="${PG_PORT:-5433}"
export PG_DATABASE="${PG_DATABASE:-a2a_connector_test}"
export PG_USER="${PG_USER:-a2a_test}"
export PG_PASSWORD="${PG_PASSWORD:-a2a_test_pwd_local_only}"
export PG_READ_ONLY="${PG_READ_ONLY:-false}"

PYTEST_ARGS="${PYTEST_ARGS:--q}"

log() { printf '[pg-tests] %s\n' "$*"; }
die() { printf '[pg-tests] ERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Step 1: ensure tests + asyncpg deps available
# ---------------------------------------------------------------------------

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c "import pytest, pytest_asyncio" 2>/dev/null \
    || die "pytest and pytest-asyncio required. Install: pip install pytest pytest-asyncio"

if ! "$PYTHON" -c "import asyncpg" 2>/dev/null; then
    log "asyncpg not installed — installing..."
    "$PYTHON" -m pip install --quiet "asyncpg>=0.30"
fi

# ---------------------------------------------------------------------------
# Step 2 (optional): bring up docker-compose Postgres
# ---------------------------------------------------------------------------

COMPOSE_UP=false

if $USE_DOCKER; then
    command -v docker >/dev/null 2>&1 || die "--docker passed but docker not on PATH"
    log "Starting docker-compose Postgres..."
    (cd "$HARNESS_DIR" && docker compose up -d)
    COMPOSE_UP=true

    # Wait up to 30s for PG to accept connections
    log "Waiting for Postgres to be ready at $PG_HOST:$PG_PORT..."
    for i in $(seq 1 30); do
        if (cd "$HARNESS_DIR" && docker compose exec -T db \
                pg_isready -U "$PG_USER" -d "$PG_DATABASE" >/dev/null 2>&1); then
            log "Postgres is ready (took ${i}s)"
            break
        fi
        if [[ "$i" == "30" ]]; then
            die "Postgres failed to become ready within 30s"
        fi
        sleep 1
    done
fi

# ---------------------------------------------------------------------------
# Step 2b: teardown trap (only if we brought the container up)
# ---------------------------------------------------------------------------

cleanup() {
    local rc=$?
    if $COMPOSE_UP && $TEARDOWN; then
        log "Tearing down docker-compose Postgres..."
        (cd "$HARNESS_DIR" && docker compose down -v) || true
    fi
    exit "$rc"
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Step 3 (optional): apply seed.sql to an existing DB
# ---------------------------------------------------------------------------

if $RUN_SEED; then
    command -v psql >/dev/null 2>&1 || die "--seed passed but psql not on PATH"
    log "Applying seed.sql to $PG_USER@$PG_HOST:$PG_PORT/$PG_DATABASE..."
    PGPASSWORD="$PG_PASSWORD" psql \
        -h "$PG_HOST" -p "$PG_PORT" \
        -U "$PG_USER" -d "$PG_DATABASE" \
        -v ON_ERROR_STOP=1 \
        -f "$HARNESS_DIR/seed.sql"
fi

# ---------------------------------------------------------------------------
# Step 4: verify reachability (fail fast with a clear message)
# ---------------------------------------------------------------------------

log "Verifying Postgres is reachable at $PG_HOST:$PG_PORT..."
"$PYTHON" -c "
import asyncio, asyncpg, sys, os
async def check():
    conn = await asyncpg.connect(
        host=os.environ['PG_HOST'], port=int(os.environ['PG_PORT']),
        database=os.environ['PG_DATABASE'],
        user=os.environ['PG_USER'], password=os.environ['PG_PASSWORD'],
        timeout=5.0,
    )
    version = await conn.fetchval('SELECT version()')
    print(f'[pg-tests] Connected: {version.split(\",\")[0]}')
    await conn.close()
asyncio.run(check())
" || die "Cannot connect to Postgres — check PG_* env vars and ensure the DB is up"

# ---------------------------------------------------------------------------
# Step 5: run the integration test suite
# ---------------------------------------------------------------------------

log "Running integration test suite..."
cd "$HARNESS_DIR"

# PYTHONPATH includes:
#   - the connector root (so tests can `from src.client import ...`)
#   - the products/ root (so src/tools.py can `import shared.src.errors` et al)
PYTHONPATH="$REPO_ROOT/products/connectors/postgres:$REPO_ROOT/products${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON" -m pytest . $PYTEST_ARGS

log "Done."
