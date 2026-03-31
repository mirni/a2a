#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Remote .deb deployment with rollback
# =============================================================================
# Deploys a .deb package to a remote server via SSH, with optional dpkg-repack
# backup and service health verification. Used by CI workflows and humans.
#
# Usage:
#   scripts/deploy.sh --host <host> --deb <file> --component <name> [OPTIONS]
#
# Required:
#   --host <host>           Target server (SSH-accessible)
#   --deb <path>            .deb file to deploy
#   --component <name>      a2a-gateway | a2a-gateway-test | a2a-website
#
# Optional:
#   --user <user>           SSH user (default: root)
#   --no-rollback           Skip dpkg-repack backup
#   --no-verify             Skip service health verification
#   --health-url <url>      Health check endpoint after deploy
#   --health-retries <n>    Retry count (default: 10)
#   --health-interval <s>   Seconds between retries (default: 5)
#   --ssh-cmd <cmd>         SSH command (default: ssh; e.g. "tailscale ssh")
#   --dry-run               Show what would happen
#   -h, --help              Show help
#
# Environment variable fallbacks:
#   DEPLOY_HOST, DEPLOY_USER, DEPLOY_DEB, DEPLOY_COMPONENT, DEPLOY_SSH_CMD
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.bash"

# ---------------------------------------------------------------------------
# Defaults (env var fallbacks)
# ---------------------------------------------------------------------------

HOST="${DEPLOY_HOST:-}"
USER="${DEPLOY_USER:-root}"
DEB="${DEPLOY_DEB:-}"
COMPONENT="${DEPLOY_COMPONENT:-}"
SSH_CMD="${DEPLOY_SSH_CMD:-ssh}"
NO_ROLLBACK=false
NO_VERIFY=false
HEALTH_URL=""
HEALTH_RETRIES=10
HEALTH_INTERVAL=5
DRY_RUN=false

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

usage() {
    sed -n '/^# Usage:/,/^# ====/p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)             HOST="$2"; shift 2 ;;
        --deb)              DEB="$2"; shift 2 ;;
        --component)        COMPONENT="$2"; shift 2 ;;
        --user)             USER="$2"; shift 2 ;;
        --ssh-cmd)          SSH_CMD="$2"; shift 2 ;;
        --no-rollback)      NO_ROLLBACK=true; shift ;;
        --no-verify)        NO_VERIFY=true; shift ;;
        --health-url)       HEALTH_URL="$2"; shift 2 ;;
        --health-retries)   HEALTH_RETRIES="$2"; shift 2 ;;
        --health-interval)  HEALTH_INTERVAL="$2"; shift 2 ;;
        --dry-run)          DRY_RUN=true; shift ;;
        -h|--help)          usage ;;
        *)                  err "Unknown option: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

[[ -n "$HOST" ]]      || err "Missing required option: --host (or set DEPLOY_HOST)"
[[ -n "$DEB" ]]       || err "Missing required option: --deb (or set DEPLOY_DEB)"
[[ -n "$COMPONENT" ]] || err "Missing required option: --component (or set DEPLOY_COMPONENT)"
[[ -f "$DEB" ]]       || err "Deb file not found: $DEB"

# Validate component name and resolve systemd service
SERVICE=$(service_for_component "$COMPONENT")

DEB_BASENAME=$(basename "$DEB")
SSH_TARGET="${USER}@${HOST}"
REMOTE_DEB="/tmp/${DEB_BASENAME}"

# ---------------------------------------------------------------------------
# Dry-run summary
# ---------------------------------------------------------------------------

if [[ "$DRY_RUN" == true ]]; then
    echo "=== DRY RUN ==="
    echo "Host:        $SSH_TARGET"
    echo "SSH cmd:     $SSH_CMD"
    echo "Deb:         $DEB → $REMOTE_DEB"
    echo "Component:   $COMPONENT"
    echo "Service:     ${SERVICE:-<none>}"
    echo "Rollback:    $( [[ "$NO_ROLLBACK" == true ]] && echo disabled || echo enabled )"
    echo "Verify:      $( [[ "$NO_VERIFY" == true ]] && echo disabled || echo enabled )"
    if [[ -n "$HEALTH_URL" ]]; then
        echo "Health URL:  $HEALTH_URL (retries=$HEALTH_RETRIES, interval=${HEALTH_INTERVAL}s)"
    fi
    echo "==============="
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 1: Copy .deb to remote server
# ---------------------------------------------------------------------------

log "Copying $DEB_BASENAME to $SSH_TARGET:$REMOTE_DEB"
# Use pipe-based transfer so any SSH command (e.g. "tailscale ssh") works.
$SSH_CMD "$SSH_TARGET" "cat > '$REMOTE_DEB'" < "$DEB"

# ---------------------------------------------------------------------------
# Step 2: Remote install with optional rollback
# ---------------------------------------------------------------------------

if [[ -n "$SERVICE" ]]; then
    # Component has a systemd service — full install with rollback
    log "Installing $DEB_BASENAME on $HOST (service: $SERVICE)"

    $SSH_CMD "$SSH_TARGET" bash -s -- \
        "$DEB_BASENAME" "$COMPONENT" "$SERVICE" "$NO_ROLLBACK" "$NO_VERIFY" \
        << 'REMOTE'
        set -euo pipefail

        DEB_BASENAME="$1"
        COMPONENT="$2"
        SERVICE="$3"
        NO_ROLLBACK="$4"
        NO_VERIFY="$5"

        # Wait for dpkg lock then install (retries for up to 120s)
        dpkg_install() {
            local deb="$1" tries=0 max_tries=24
            while (( tries < max_tries )); do
                if dpkg -i "$deb"; then
                    return 0
                fi
                if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
                    return 1  # failed for a reason other than lock
                fi
                tries=$((tries + 1))
                echo "[!] dpkg lock held, retrying ($tries/$max_tries)..."
                sleep 5
            done
            echo "[x] dpkg lock held for >120s, giving up"
            return 1
        }

        BACKUP_DIR="/var/backups/a2a/deploy-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_DIR"

        # --- Backup current package for rollback ---
        if [[ "$NO_ROLLBACK" != true ]] && dpkg -s "$COMPONENT" >/dev/null 2>&1; then
            echo "[+] Backing up current $COMPONENT package..."
            dpkg-query -W -f='${Package}_${Version}_${Architecture}.deb\n' "$COMPONENT" \
                > "$BACKUP_DIR/previous_version.txt" || true
            dpkg-repack "$COMPONENT" 2>/dev/null && mv "${COMPONENT}"_*.deb "$BACKUP_DIR/" || true
        fi

        # --- Install new package ---
        echo "[+] Installing /tmp/$DEB_BASENAME..."
        if dpkg_install "/tmp/$DEB_BASENAME"; then
            echo "[+] Package installed successfully"
        else
            echo "[x] dpkg -i failed — attempting rollback"
            ROLLBACK_DEB=$(ls "$BACKUP_DIR"/"${COMPONENT}"_*.deb 2>/dev/null | head -1)
            if [[ -n "${ROLLBACK_DEB:-}" ]]; then
                dpkg_install "$ROLLBACK_DEB"
                systemctl restart "$SERVICE" || true
            fi
            exit 1
        fi

        # --- Verify service is running ---
        if [[ "$NO_VERIFY" != true ]]; then
            sleep 3
            if systemctl is-active "$SERVICE"; then
                echo "[+] Service $SERVICE is active"
            else
                echo "[x] Service $SERVICE failed to start — rolling back"
                ROLLBACK_DEB=$(ls "$BACKUP_DIR"/"${COMPONENT}"_*.deb 2>/dev/null | head -1)
                if [[ -n "${ROLLBACK_DEB:-}" ]]; then
                    dpkg_install "$ROLLBACK_DEB"
                    systemctl restart "$SERVICE" || true
                fi
                exit 1
            fi
        fi

        rm -f "/tmp/$DEB_BASENAME"
REMOTE

else
    # Component has no systemd service (e.g. website) — simple install
    log "Installing $DEB_BASENAME on $HOST (no service)"

    $SSH_CMD "$SSH_TARGET" bash -s -- \
        "$DEB_BASENAME" "$COMPONENT" "$NO_ROLLBACK" \
        << 'REMOTE'
        set -euo pipefail

        DEB_BASENAME="$1"
        COMPONENT="$2"
        NO_ROLLBACK="$3"

        # Wait for dpkg lock then install (retries for up to 120s)
        dpkg_install() {
            local deb="$1" tries=0 max_tries=24
            while (( tries < max_tries )); do
                if dpkg -i "$deb"; then
                    return 0
                fi
                if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
                    return 1  # failed for a reason other than lock
                fi
                tries=$((tries + 1))
                echo "[!] dpkg lock held, retrying ($tries/$max_tries)..."
                sleep 5
            done
            echo "[x] dpkg lock held for >120s, giving up"
            return 1
        }

        BACKUP_DIR="/var/backups/a2a/deploy-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP_DIR"

        # --- Backup current package for rollback ---
        if [[ "$NO_ROLLBACK" != true ]] && dpkg -s "$COMPONENT" >/dev/null 2>&1; then
            echo "[+] Backing up current $COMPONENT package..."
            dpkg-repack "$COMPONENT" 2>/dev/null && mv "${COMPONENT}"_*.deb "$BACKUP_DIR/" || true
        fi

        # --- Install new package ---
        echo "[+] Installing /tmp/$DEB_BASENAME..."
        if dpkg_install "/tmp/$DEB_BASENAME"; then
            echo "[+] Package installed successfully"
        else
            echo "[x] dpkg -i failed — rolling back"
            ROLLBACK_DEB=$(ls "$BACKUP_DIR"/"${COMPONENT}"_*.deb 2>/dev/null | head -1)
            if [[ -n "${ROLLBACK_DEB:-}" ]]; then
                dpkg_install "$ROLLBACK_DEB"
            fi
            exit 1
        fi

        rm -f "/tmp/$DEB_BASENAME"
REMOTE

fi

log "Deployment of $COMPONENT to $HOST completed"

# ---------------------------------------------------------------------------
# Step 3: Optional health check
# ---------------------------------------------------------------------------

if [[ -n "$HEALTH_URL" ]]; then
    log "Running health check against $HEALTH_URL"
    "$SCRIPT_DIR/deploy_healthcheck.sh" \
        --url "$HEALTH_URL" \
        --retries "$HEALTH_RETRIES" \
        --interval "$HEALTH_INTERVAL"
fi

log "Done."
