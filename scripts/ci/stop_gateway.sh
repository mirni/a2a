#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Stop local gateway and clean up
#
# Usage:
#   scripts/ci/stop_gateway.sh [pid]
#
# Falls back to $SERVER_PID env var if no argument given.
# =============================================================================

set -uo pipefail  # no -e: this script must never fail

PID="${1:-${SERVER_PID:-}}"
DATA_DIR="${A2A_DATA_DIR:-}"

if [[ -n "$PID" ]]; then
    kill "$PID" 2>/dev/null || true
    echo "Stopped gateway (pid $PID)"
fi

if [[ -n "$DATA_DIR" && -d "$DATA_DIR" ]]; then
    rm -rf "$DATA_DIR"
    echo "Cleaned up $DATA_DIR"
fi

exit 0
