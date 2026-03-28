#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Start local gateway for CI/testing
#
# Env vars (optional):
#   GATEWAY_HOST      — bind address (default: 127.0.0.1)
#   GATEWAY_PORT      — port (default: 8000)
#   GATEWAY_MAX_WAIT  — health check timeout in seconds (default: 30)
#
# Outputs (written to $GITHUB_ENV if in CI, printed to stdout otherwise):
#   A2A_DATA_DIR  — temp data directory
#   SERVER_PID    — uvicorn process PID
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

HOST="${GATEWAY_HOST:-127.0.0.1}"
PORT="${GATEWAY_PORT:-8000}"
MAX_WAIT="${GATEWAY_MAX_WAIT:-30}"

# Create temp data dir
A2A_DATA_DIR=$(mktemp -d)
export A2A_DATA_DIR

# Start server in background
PYTHONPATH="$REPO_ROOT" \
    python -m uvicorn gateway.main:app \
        --host "$HOST" --port "$PORT" --workers 1 --log-level warning &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server on ${HOST}:${PORT}..."
for i in $(seq 1 "$MAX_WAIT"); do
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo "Server process crashed" >&2
        exit 1
    fi
    if curl -sf "http://${HOST}:${PORT}/v1/health" > /dev/null 2>&1; then
        echo "Server ready after ${i}s"
        break
    fi
    if [[ "$i" -eq "$MAX_WAIT" ]]; then
        echo "Server failed to start within ${MAX_WAIT}s" >&2
        kill "$SERVER_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Export to CI or print for local use
if [[ -n "${GITHUB_ENV:-}" ]]; then
    echo "A2A_DATA_DIR=$A2A_DATA_DIR" >> "$GITHUB_ENV"
    echo "SERVER_PID=$SERVER_PID" >> "$GITHUB_ENV"
else
    echo "A2A_DATA_DIR=$A2A_DATA_DIR"
    echo "SERVER_PID=$SERVER_PID"
fi
