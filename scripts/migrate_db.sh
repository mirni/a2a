#!/usr/bin/env bash
# =============================================================================
# Atomic database migration script for A2A Commerce Platform.
#
# For each product with schema migrations:
#   1. Resolve DB path from env var (or default)
#   2. Skip if DB doesn't exist (fresh install — app creates it on first run)
#   3. Use SQLite backup API to create shadow.db (clean, no WAL)
#   4. Run pending migrations on shadow.db
#   5. Validate shadow.db (integrity_check + version check)
#   6. On failure: remove shadow, mark as failed, continue next product
#   7. On success: mv shadow → production DB (atomic on same filesystem)
#   8. Exit non-zero if any product failed
#
# Usage:
#   scripts/migrate_db.sh          # run all product migrations
#   scripts/migrate_db.sh --dry    # show what would happen, don't migrate
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/common.bash"

# Python interpreter — prefer the deployed venv, then local .venv, then system
PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
    for candidate in \
        "$INSTALL_DIR/venv/bin/python" \
        "$REPO_ROOT/venv/bin/python" \
        "$REPO_ROOT/.venv/bin/python" \
        python3; do
        if [[ -x "$candidate" ]]; then
            PYTHON="$candidate"
            break
        fi
    done
fi

if [[ -z "$PYTHON" ]]; then
    err "No Python interpreter found"
fi

# Verify aiosqlite is available
if ! "$PYTHON" -c "import aiosqlite" 2>/dev/null; then
    err "aiosqlite not installed in $PYTHON — run from the application venv"
fi

HELPER="$SCRIPT_DIR/migrate_db_helper.py"
DRY_RUN=false
[[ "${1:-}" == "--dry" ]] && DRY_RUN=true

FAILED=0
SERVICE_STOPPED=false

stop_service() {
    if ! $SERVICE_STOPPED; then
        if systemctl is-active --quiet a2a-gateway 2>/dev/null; then
            log "Stopping a2a-gateway for atomic swap..."
            systemctl stop a2a-gateway
            SERVICE_STOPPED=true
        fi
    fi
}

restart_service() {
    if $SERVICE_STOPPED; then
        log "Restarting a2a-gateway..."
        systemctl start a2a-gateway
        SERVICE_STOPPED=false
    fi
}

# ---------------------------------------------------------------------------
# Get current DB version using sqlite3 CLI (no Python deps needed)
# ---------------------------------------------------------------------------

get_db_version() {
    local db_path="$1"
    # Check if schema_migrations table exists and query max version
    local version
    version=$(sqlite3 "$db_path" \
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations;" 2>/dev/null \
        || echo "0")
    echo "$version"
}

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

while IFS=: read -r product env_var default_path expected_version; do
    db_path="${!env_var:-$default_path}"

    if [[ ! -f "$db_path" ]]; then
        log "$product: DB not found at $db_path (fresh install, skipping)"
        continue
    fi

    current_version=$(get_db_version "$db_path")

    if [[ "$current_version" == "$expected_version" ]]; then
        log "$product: already at v$expected_version (skipping)"
        continue
    fi

    if [[ "$current_version" -gt "$expected_version" ]]; then
        warn "$product: DB at v$current_version is ahead of code v$expected_version (OK, skipping)"
        continue
    fi

    log "$product: v$current_version → v$expected_version"

    if $DRY_RUN; then
        warn "$product: --dry mode, skipping actual migration"
        continue
    fi

    shadow="${db_path}.shadow"
    rm -f "$shadow"

    # 1. Create shadow copy using sqlite3 backup API (clean, no WAL)
    if ! sqlite3 "$db_path" ".backup '$shadow'" 2>/dev/null; then
        warn "$product: failed to create shadow copy"
        rm -f "$shadow"
        FAILED=1
        continue
    fi

    # 2. Run migrations on shadow
    if ! "$PYTHON" "$HELPER" migrate "$shadow" "$product"; then
        warn "$product: migration failed on shadow copy"
        rm -f "$shadow"
        FAILED=1
        continue
    fi

    # 3. Validate shadow
    if ! "$PYTHON" "$HELPER" validate "$shadow" "$product"; then
        warn "$product: validation failed on shadow copy"
        rm -f "$shadow"
        FAILED=1
        continue
    fi

    # 4. Stop service before atomic swap (only once across all products)
    stop_service

    # 5. Atomic swap
    mv "$shadow" "$db_path"

    # Preserve ownership if running as root
    if [[ $EUID -eq 0 ]]; then
        chown "${A2A_USER}:${A2A_GROUP}" "$db_path" 2>/dev/null || true
    fi

    log "$product: migrated to v$expected_version"

done < <("$PYTHON" "$HELPER" list-products)

# ---------------------------------------------------------------------------
# Restart service if we stopped it
# ---------------------------------------------------------------------------

restart_service

if [[ $FAILED -ne 0 ]]; then
    err "One or more migrations failed — see above"
fi

log "All migrations complete"
