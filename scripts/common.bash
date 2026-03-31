#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Shared deployment functions and configuration
# Source this file from other deployment scripts:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.bash"
# =============================================================================

# Prevent double-sourcing
[[ -n "${_A2A_COMMON_LOADED:-}" ]] && return 0
_A2A_COMMON_LOADED=1

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (override via environment variables)
# ---------------------------------------------------------------------------

DOMAIN="${A2A_DOMAIN:-api.greenhelix.net}"
WWW_DOMAIN="${A2A_WWW_DOMAIN:-greenhelix.net}"
BRANCH="${A2A_BRANCH:-main}"
GITHUB_PAT="${GITHUB_PAT:-}"
TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"

INSTALL_DIR="/opt/a2a"
DATA_DIR="/var/lib/a2a"
A2A_USER="a2a"
A2A_GROUP="a2a"
PORT=8000

SSL_DIR="/etc/ssl"
SSL_CERT="$SSL_DIR/certs/greenhelix.pem"
SSL_KEY="$SSL_DIR/private/greenhelix.key"

BACKUP_DIR="/var/backups/a2a"

# ---------------------------------------------------------------------------
# Colors and logging
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

require_root() {
    [[ $EUID -eq 0 ]] || err "This script must be run as root (sudo $0)"
}

# ---------------------------------------------------------------------------
# APT helpers (cloud-init compatible)
# ---------------------------------------------------------------------------

_wait_for_apt() {
    local tries=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
          fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
        if (( tries++ > 60 )); then
            err "apt lock held for >5 minutes, aborting"
        fi
        echo "Waiting for apt lock (attempt $tries)..."
        sleep 5
    done
}

_apt_get() {
    _wait_for_apt
    DEBIAN_FRONTEND=noninteractive apt-get \
        -o DPkg::Lock::Timeout=60 \
        -o Dpkg::Options::="--force-confdef" \
        -o Dpkg::Options::="--force-confold" \
        "$@"
}

# ---------------------------------------------------------------------------
# SSL helpers
# ---------------------------------------------------------------------------

# Check if Cloudflare Origin Server certificates are installed
has_ssl_certs() {
    [[ -f "$SSL_CERT" && -f "$SSL_KEY" ]]
}

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

repo_url() {
    if [[ -n "$GITHUB_PAT" ]]; then
        echo "${A2A_REPO_URL:-https://x-access-token:${GITHUB_PAT}@github.com/mirni/a2a.git}"
    else
        echo "${A2A_REPO_URL:-https://github.com/mirni/a2a.git}"
    fi
}

# Strip embedded PAT from git remote so it's not persisted on disk
strip_pat_from_remote() {
    if [[ -n "$GITHUB_PAT" && -d "$INSTALL_DIR/.git" ]]; then
        local clean_url
        clean_url=$(cd "$INSTALL_DIR" && git remote get-url origin | sed 's|//x-access-token:[^@]*@|//|')
        cd "$INSTALL_DIR" && git remote set-url origin "$clean_url"
        log "Stripped PAT from git remote"
    fi
}

# ---------------------------------------------------------------------------
# Nginx helpers
# ---------------------------------------------------------------------------

# Add rate limit zone to nginx.conf if not present
ensure_nginx_rate_limit() {
    if ! grep -q 'a2a_limit' /etc/nginx/nginx.conf 2>/dev/null; then
        sed -i '/http {/a\    limit_req_zone \$binary_remote_addr zone=a2a_limit:10m rate=30r/s;' \
            /etc/nginx/nginx.conf
    fi
}

# ---------------------------------------------------------------------------
# Component → systemd service mapping
# ---------------------------------------------------------------------------

# Map a deployment component name to its systemd service.
# Returns empty string for components with no service (e.g. a2a-website).
service_for_component() {
    local component="$1"
    case "$component" in
        a2a-gateway)      echo "a2a-gateway" ;;
        a2a-gateway-test) echo "a2a-gateway-test" ;;
        a2a-website)      echo "" ;;
        *)                err "Unknown component: $component" ;;
    esac
}

# Enable a site and reload nginx
enable_nginx_site() {
    local name="$1"
    ln -sf "/etc/nginx/sites-available/$name" "/etc/nginx/sites-enabled/$name"
    nginx -t && systemctl reload nginx
}
