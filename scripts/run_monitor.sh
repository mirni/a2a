#!/usr/bin/env bash
# =============================================================================
# A2A Monitoring Stack — Docker Compose wrapper
#
# Usage:
#   scripts/run_monitor.sh              # start stack (foreground)
#   scripts/run_monitor.sh up           # start stack (detached)
#   scripts/run_monitor.sh down         # stop stack
#   scripts/run_monitor.sh status       # show container status
#   scripts/run_monitor.sh logs         # tail logs
#   scripts/run_monitor.sh restart      # restart all services
#   scripts/run_monitor.sh clean        # stop + remove volumes (full reset)
#   scripts/run_monitor.sh check        # verify gateway reachability
#
# Environment variables:
#   A2A_GATEWAY_HOST   Gateway host (default: auto-detect)
#   A2A_GATEWAY_PORT   Gateway port (default: 443)
#   GRAFANA_PORT       Grafana port (default: 3030)
#   PROMETHEUS_PORT    Prometheus port (default: 9090)
#   GRAFANA_ADMIN_USER     Grafana admin user (default: admin)
#   GRAFANA_ADMIN_PASSWORD Grafana admin password (default: admin)
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MONITOR_DIR="$REPO_ROOT/monitoring"

if [ ! -f "$MONITOR_DIR/docker-compose.yml" ]; then
    echo "Error: monitoring/docker-compose.yml not found" >&2
    exit 1
fi

# Load local overrides (not checked in — contains Tailscale IP, etc.)
if [ -f "$MONITOR_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$MONITOR_DIR/.env"
    set +a
fi

# Check docker compose is available
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif docker-compose version >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "Error: docker compose not found. Install Docker with Compose plugin." >&2
    exit 1
fi

# Gateway host: default to the live server. Override with A2A_GATEWAY_HOST env
# var for local development (e.g. A2A_GATEWAY_HOST=localhost).
if [ -z "${A2A_GATEWAY_HOST:-}" ]; then
    A2A_GATEWAY_HOST="api.greenhelix.net"
fi
export A2A_GATEWAY_HOST
export A2A_GATEWAY_PORT="${A2A_GATEWAY_PORT:-443}"
# Derive scheme from port: 443 → https, anything else → http
if [ "$A2A_GATEWAY_PORT" = "443" ]; then
    export A2A_GATEWAY_SCHEME="${A2A_GATEWAY_SCHEME:-https}"
else
    export A2A_GATEWAY_SCHEME="${A2A_GATEWAY_SCHEME:-http}"
fi
export GRAFANA_PORT="${GRAFANA_PORT:-3030}"
export PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"

# Generate prometheus.yml from template
PROM_TMPL="$MONITOR_DIR/prometheus/prometheus.yml.tmpl"
PROM_YML="$MONITOR_DIR/prometheus/prometheus.yml"
if [ ! -f "$PROM_TMPL" ]; then
    echo "Error: $PROM_TMPL not found" >&2
    exit 1
fi
envsubst '${A2A_GATEWAY_HOST} ${A2A_GATEWAY_PORT} ${A2A_GATEWAY_SCHEME}' < "$PROM_TMPL" > "$PROM_YML"

CMD="${1:-up}"

case "$CMD" in
    up)
        echo "Starting A2A monitoring stack..."
        echo "  Gateway:    ${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}"
        echo "  Prometheus: http://localhost:${PROMETHEUS_PORT}"
        echo "  Grafana:    http://localhost:${GRAFANA_PORT} (admin/admin)"
        echo ""
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" up -d
        echo ""
        # Quick reachability check (non-blocking)
        echo "Checking gateway reachability..."
        if curl -sf -o /dev/null -m 3 "https://${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}/v1/health"; then
            echo "  Gateway ${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT} is reachable."
        else
            echo "  WARNING: Cannot reach gateway at ${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}"
            echo "  Ensure the gateway is running and bound to 0.0.0.0 (not 127.0.0.1)."
            echo "  You can override with: A2A_GATEWAY_HOST=<ip> scripts/run_monitor.sh up"
        fi
        echo ""
        echo "Stack is running. Use 'scripts/run_monitor.sh logs' to tail logs."
        ;;
    down)
        echo "Stopping monitoring stack..."
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" down
        ;;
    status)
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" ps
        ;;
    logs)
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" logs -f --tail=50
        ;;
    restart)
        echo "Restarting monitoring stack..."
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" restart
        ;;
    clean)
        echo "Stopping and removing all monitoring data..."
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" down -v
        echo "Done. All Prometheus and Grafana data has been removed."
        ;;
    check)
        echo "=== Monitoring Stack Diagnostics ==="
        echo ""
        echo "1. Gateway target: ${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}"
        echo "   Generated config: $(grep -o 'targets:.*' "$PROM_YML" | head -1)"
        echo ""

        echo "2. Gateway reachability (from host):"
        if curl -sf -o /dev/null -m 3 "https://${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}/v1/health"; then
            echo "   OK — gateway responds at ${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}"
        else
            echo "   FAIL — cannot reach https://${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}/v1/health"
            echo "   Is the gateway running? Is it bound to 0.0.0.0?"
        fi
        echo ""

        echo "3. Gateway reachability (from Prometheus container):"
        if docker exec a2a-prometheus wget -q -O /dev/null -T 3 \
            "https://${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}/v1/health" 2>/dev/null; then
            echo "   OK — Prometheus container can reach the gateway"
        else
            echo "   FAIL — Prometheus container cannot reach ${A2A_GATEWAY_HOST}:${A2A_GATEWAY_PORT}"
            echo "   The gateway may be bound to 127.0.0.1. Restart it with --host 0.0.0.0"
        fi
        echo ""

        echo "4. Prometheus scrape targets:"
        TARGETS_JSON=$(curl -sf -m 3 "http://localhost:${PROMETHEUS_PORT}/api/v1/targets" 2>/dev/null)
        if [ -n "$TARGETS_JSON" ]; then
            echo "$TARGETS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data.get('data', {}).get('activeTargets', []):
    job = t.get('labels', {}).get('job', '?')
    health = t.get('health', '?')
    url = t.get('scrapeUrl', '?')
    err = t.get('lastError', '')
    status = 'OK' if health == 'up' else 'FAIL'
    print(f'   [{status}] {job}: {url} — {health}')
    if err:
        print(f'         Error: {err}')
" 2>/dev/null || echo "   (could not parse targets response)"
        else
            echo "   Cannot reach Prometheus at localhost:${PROMETHEUS_PORT}"
        fi
        ;;
    *)
        echo "Usage: scripts/run_monitor.sh [up|down|status|logs|restart|clean|check]"
        exit 1
        ;;
esac
