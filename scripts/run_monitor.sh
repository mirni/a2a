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
#
# Environment variables:
#   A2A_GATEWAY_HOST   Gateway host (default: auto-detect)
#   A2A_GATEWAY_PORT   Gateway port (default: 8000)
#   GRAFANA_PORT       Grafana port (default: 3000)
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

# Check docker compose is available
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif docker-compose version >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "Error: docker compose not found. Install Docker with Compose plugin." >&2
    exit 1
fi

# Auto-detect gateway host for Linux (no Docker Desktop → host.docker.internal
# doesn't work by default, but we add extra_hosts in compose).
export A2A_GATEWAY_PORT="${A2A_GATEWAY_PORT:-8000}"
export GRAFANA_PORT="${GRAFANA_PORT:-3000}"
export PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"

CMD="${1:-up}"

case "$CMD" in
    up)
        echo "Starting A2A monitoring stack..."
        echo "  Prometheus: http://localhost:${PROMETHEUS_PORT}"
        echo "  Grafana:    http://localhost:${GRAFANA_PORT} (admin/admin)"
        echo ""
        $COMPOSE -f "$MONITOR_DIR/docker-compose.yml" up -d
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
    *)
        echo "Usage: scripts/run_monitor.sh [up|down|status|logs|restart|clean]"
        exit 1
        ;;
esac
