#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Health check retry loop
# Waits for a URL to return HTTP 2xx, retrying on failure.
#
# Usage:
#   scripts/deploy_healthcheck.sh --url <url> [--retries N] [--interval S]
#
# Options:
#   --url <url>         Health check endpoint (required)
#   --retries <n>       Number of attempts (default: 10)
#   --interval <s>      Seconds between retries (default: 5)
#   -h, --help          Show this help message
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.bash"

URL=""
RETRIES=10
INTERVAL=5

usage() {
    sed -n '/^# Usage:/,/^# ====/p' "$0" | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --url)      URL="$2"; shift 2 ;;
        --retries)  RETRIES="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        -h|--help)  usage ;;
        *)          err "Unknown option: $1" ;;
    esac
done

[[ -n "$URL" ]] || err "Missing required option: --url <url>"

for i in $(seq 1 "$RETRIES"); do
    http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL" 2>/dev/null || echo "000")
    if [[ "$http_code" =~ ^2 ]]; then
        log "Health check passed (attempt $i/$RETRIES, HTTP $http_code)"
        exit 0
    fi
    warn "Health check attempt $i/$RETRIES failed (HTTP $http_code), retrying in ${INTERVAL}s..."
    sleep "$INTERVAL"
done

# Final verbose attempt for diagnostics
warn "Final diagnostic attempt:"
curl -sv --max-time 10 "$URL" 2>&1 || true

err "Health check failed after $RETRIES attempts: $URL"
