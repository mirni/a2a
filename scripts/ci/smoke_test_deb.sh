#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Post-package, pre-deploy smoke test
# =============================================================================
# Extracts the built .deb and verifies the installed artifact actually boots
# and serves a few public endpoints. Runs BEFORE staging deploy so packaging
# regressions are caught before we push to a real host.
#
# Usage:
#   scripts/ci/smoke_test_deb.sh dist/a2a-gateway_*.deb
# =============================================================================

set -euo pipefail

DEB_FILE="${1:-}"
if [[ -z "$DEB_FILE" ]] || [[ ! -f "$DEB_FILE" ]]; then
    echo "Usage: $0 <path-to-deb>" >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${SMOKE_PORT:-8765}"
EXTRACT_DIR="$(mktemp -d)"
DATA_DIR="$(mktemp -d)"
LOG_FILE="$(mktemp)"
SERVER_PID=""

cleanup() {
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    rm -rf "$EXTRACT_DIR" "$DATA_DIR" "$LOG_FILE"
}
trap cleanup EXIT

log() { echo -e "\033[0;36m[smoke]\033[0m $*"; }
ok()  { echo -e "\033[0;32m[ ok ]\033[0m $*"; }
err() { echo -e "\033[0;31m[FAIL]\033[0m $*" >&2; }

# -----------------------------------------------------------------------------
# Step 1: Extract the deb
# -----------------------------------------------------------------------------
log "Extracting $DEB_FILE..."
dpkg-deb -x "$DEB_FILE" "$EXTRACT_DIR"

APP_DIR="$EXTRACT_DIR/opt/a2a"
if [[ ! -d "$APP_DIR/gateway" ]]; then
    err "Missing $APP_DIR/gateway — deb structure is broken"
    ls -la "$APP_DIR" 2>&1 || true
    exit 1
fi
ok "deb structure valid"

# -----------------------------------------------------------------------------
# Step 2: Verify required files exist
# -----------------------------------------------------------------------------
for required in \
    "opt/a2a/gateway/main.py" \
    "opt/a2a/gateway/src/app.py" \
    "opt/a2a/pricing.json" \
    "etc/systemd/system/a2a-gateway.service" \
; do
    if [[ ! -e "$EXTRACT_DIR/$required" ]]; then
        err "Missing required file: $required"
        exit 1
    fi
done
ok "required files present"

# -----------------------------------------------------------------------------
# Step 3: Create minimal env file pointing at temp data dir
# -----------------------------------------------------------------------------
cat > "$APP_DIR/.env" <<ENVEOF
HOST=127.0.0.1
PORT=$PORT
A2A_DATA_DIR=$DATA_DIR
BILLING_DSN=sqlite:///$DATA_DIR/billing.db
PAYWALL_DSN=sqlite:///$DATA_DIR/paywall.db
PAYMENTS_DSN=sqlite:///$DATA_DIR/payments.db
MARKETPLACE_DSN=sqlite:///$DATA_DIR/marketplace.db
TRUST_DSN=sqlite:///$DATA_DIR/trust.db
EVENT_BUS_DSN=sqlite:///$DATA_DIR/events.db
WEBHOOK_DSN=sqlite:///$DATA_DIR/webhooks.db
IDENTITY_DSN=sqlite:///$DATA_DIR/identity.db
MESSAGING_DSN=sqlite:///$DATA_DIR/messaging.db
DISPUTE_DSN=sqlite:///$DATA_DIR/disputes.db
LOG_LEVEL=WARNING
ENVEOF

# -----------------------------------------------------------------------------
# Step 4: Run migrations
# -----------------------------------------------------------------------------
log "Running database migrations..."
if [[ -x "$REPO_ROOT/scripts/migrate_db.sh" ]]; then
    A2A_DATA_DIR="$DATA_DIR" PYTHONPATH="$APP_DIR" \
        "$REPO_ROOT/scripts/migrate_db.sh" >/dev/null 2>&1 \
        || log "migrations skipped (not required for health probe)"
fi

# -----------------------------------------------------------------------------
# Step 5: Start uvicorn from the extracted deb content
# -----------------------------------------------------------------------------
log "Starting gateway from extracted deb on port $PORT..."
# shellcheck disable=SC1091
set -a
. "$APP_DIR/.env"
set +a

PYTHONPATH="$APP_DIR" python -m uvicorn gateway.main:app \
    --host 127.0.0.1 \
    --port "$PORT" \
    --workers 1 \
    --log-level warning \
    > "$LOG_FILE" 2>&1 &
SERVER_PID=$!

# -----------------------------------------------------------------------------
# Step 6: Wait for server to be ready
# -----------------------------------------------------------------------------
log "Waiting for server (pid=$SERVER_PID)..."
for i in $(seq 1 30); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        err "Server crashed during startup"
        echo "--- last 50 lines of log ---"
        tail -n 50 "$LOG_FILE"
        exit 1
    fi
    if curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then
        ok "Server ready after ${i}s"
        break
    fi
    if [[ $i -eq 30 ]]; then
        err "Server did not become ready within 30s"
        echo "--- last 50 lines of log ---"
        tail -n 50 "$LOG_FILE"
        exit 1
    fi
    sleep 1
done

# -----------------------------------------------------------------------------
# Step 7: Exercise public endpoints
# -----------------------------------------------------------------------------
FAILED=0

probe() {
    local path="$1"
    local expected_status="${2:-200}"
    local actual
    actual=$(curl -sS -o /tmp/smoke-body -w "%{http_code}" "http://127.0.0.1:$PORT$path" 2>/dev/null || echo "000")
    if [[ "$actual" == "$expected_status" ]]; then
        ok "GET $path → $actual"
    else
        err "GET $path → expected $expected_status, got $actual"
        head -c 400 /tmp/smoke-body; echo
        FAILED=1
    fi
}

log "Probing endpoints..."
probe "/v1/health"                    "200"
probe "/v1/pricing"                   "200"
probe "/.well-known/agent-card.json"  "200"
probe "/v1/openapi.json"              "200"
probe "/v1/nonexistent"               "404"

# Verify pricing returns JSON with the keys our pricing config has
if ! curl -sS "http://127.0.0.1:$PORT/v1/pricing" | python -c "import sys,json; d=json.load(sys.stdin); assert 'tools' in d and len(d['tools']) > 0, d; print('pricing schema OK')"; then
    err "pricing response missing expected keys"
    FAILED=1
fi

# Verify health returns ok status
if ! curl -sS "http://127.0.0.1:$PORT/v1/health" | python -c "import sys,json; d=json.load(sys.stdin); assert d.get('status') == 'ok', d; print('health OK')"; then
    err "health response not 'ok'"
    FAILED=1
fi

# -----------------------------------------------------------------------------
# Step 8: Stop server cleanly
# -----------------------------------------------------------------------------
log "Stopping server..."
kill "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
SERVER_PID=""

if [[ $FAILED -ne 0 ]]; then
    err "Smoke test FAILED"
    exit 1
fi

ok "All smoke checks passed"
