#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Main deployment orchestrator
# Replaces the monolithic deploy.sh. Called from deb postinst or directly.
#
# Usage:
#   sudo ./deploy_a2a.sh                                     # public repo
#   sudo A2A_DOMAIN=api.example.com ./deploy_a2a.sh          # with domain
#   sudo A2A_SKIP_GIT=1 ./deploy_a2a.sh                      # skip git (deb)
#
# Environment variables:
#   A2A_DOMAIN          — gateway domain (default: a2a.example.com)
#   A2A_WWW_DOMAIN      — website domain (optional, enables website deploy)
#   A2A_BRANCH          — git branch (default: main)
#   GITHUB_PAT          — GitHub PAT for private repo access
#   TAILSCALE_AUTHKEY   — Tailscale auth key (optional)
#   A2A_SKIP_GIT        — set to 1 to skip git clone/pull (used by deb postinst)
#   A2A_SKIP_APT        — set to 1 to skip apt install (used by deb postinst)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.bash"
require_root

# ---------------------------------------------------------------------------
# Logging and error handling
# ---------------------------------------------------------------------------

exec > >(tee -a /var/log/a2a-deploy.log) 2>&1
echo "=== deploy_a2a.sh started at $(date -u) ==="

export HOME="${HOME:-/root}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

trap 'echo "FAILED at line $LINENO (exit code $?)" | tee -a /var/log/a2a-deploy.log' ERR

log "Starting A2A Commerce Platform deployment on $(lsb_release -ds 2>/dev/null || echo 'Ubuntu')"

# ---------------------------------------------------------------------------
# Step 1: System packages (skip when called from deb postinst — dpkg holds lock)
# ---------------------------------------------------------------------------

if [[ "${A2A_SKIP_APT:-0}" != "1" ]]; then
    log "Updating system packages..."
    export DEBIAN_FRONTEND=noninteractive
    _apt_get update -qq
    _apt_get upgrade -y -qq

    log "Installing system dependencies..."
    _apt_get install -y -qq \
        python3.12 python3.12-venv python3.12-dev python3-pip \
        nginx sqlite3 git curl ufw
else
    log "A2A_SKIP_APT=1 — skipping apt (dependencies satisfied via deb Depends:)"
fi

# ---------------------------------------------------------------------------
# Step 2: Create user and directories
# ---------------------------------------------------------------------------

"$SCRIPT_DIR/create_user.sh"

# ---------------------------------------------------------------------------
# Step 3: Git clone/pull (skip if A2A_SKIP_GIT=1, e.g. deb install)
# ---------------------------------------------------------------------------

if [[ "${A2A_SKIP_GIT:-0}" != "1" ]]; then
    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log "Updating existing repository..."
        cd "$INSTALL_DIR"
        git fetch origin
        git checkout "$BRANCH"
        git pull origin "$BRANCH"
    else
        log "Cloning repository..."
        git clone --branch "$BRANCH" "$(repo_url)" "$INSTALL_DIR"
    fi
    strip_pat_from_remote
else
    log "A2A_SKIP_GIT=1 — skipping git operations (code installed from deb)"
fi

# ---------------------------------------------------------------------------
# Step 4: Deploy gateway
# ---------------------------------------------------------------------------

"$SCRIPT_DIR/deploy_a2a-gateway.sh"

# ---------------------------------------------------------------------------
# Step 5: Deploy website (if configured)
# ---------------------------------------------------------------------------

"$SCRIPT_DIR/deploy_website.sh"

# ---------------------------------------------------------------------------
# Step 6: Tailscale (optional)
# ---------------------------------------------------------------------------

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh

    log "Starting Tailscale with SSH enabled..."
    tailscale up --authkey="$TAILSCALE_AUTHKEY" --ssh --hostname="a2a-gateway"

    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "pending")
    log "Tailscale connected. IP: $TAILSCALE_IP"
else
    warn "TAILSCALE_AUTHKEY not set — skipping Tailscale setup"
fi

# ---------------------------------------------------------------------------
# Step 7: Firewall (ufw)
# ---------------------------------------------------------------------------

log "Configuring firewall..."
ufw --force reset >/dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    ufw allow from 100.64.0.0/10 to any port 22
    ufw allow 41641/udp
    ufw allow 2222/tcp
    log "SSH restricted to Tailscale network. Emergency fallback on port 2222."
else
    ufw allow ssh
fi

ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ---------------------------------------------------------------------------
# Step 8: SSH hardening (if Tailscale)
# ---------------------------------------------------------------------------

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    log "Configuring emergency SSH fallback on port 2222..."

    if ! grep -q "^Port 2222" /etc/ssh/sshd_config; then
        if grep -q "^Port " /etc/ssh/sshd_config; then
            sed -i '/^Port /a Port 2222' /etc/ssh/sshd_config
        else
            echo "Port 22" >> /etc/ssh/sshd_config
            echo "Port 2222" >> /etc/ssh/sshd_config
        fi
    fi

    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config

    _apt_get install -y -qq fail2ban
    cat > /etc/fail2ban/jail.d/sshd-fallback.conf << 'F2BEOF'
[sshd]
enabled = true
port = 22,2222
maxretry = 3
bantime = 3600
findtime = 600
F2BEOF
    systemctl enable fail2ban
    systemctl restart fail2ban
    systemctl restart sshd
    log "fail2ban active on ports 22,2222 (3 strikes = 1h ban)"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo "=== deploy_a2a.sh finished at $(date -u) ==="
touch /var/log/a2a-deploy-done

PROTO="http"
has_ssl_certs && PROTO="https"

echo ""
echo "============================================================================="
echo -e "${GREEN} A2A Commerce Platform — Deployment Complete${NC}"
echo "============================================================================="
echo ""
echo "  Gateway:    ${PROTO}://$DOMAIN"
if [[ -n "$WWW_DOMAIN" ]]; then
echo "  Website:    ${PROTO}://$WWW_DOMAIN"
fi
echo "  Data dir:   $DATA_DIR"
echo "  Logs:       journalctl -u a2a-gateway -f"
echo "  Config:     $INSTALL_DIR/.env"
echo ""

if [[ -n "${A2A_ADMIN_KEY:-}" ]]; then
echo "  Admin key:  $A2A_ADMIN_KEY"
echo ""
fi

if [[ -n "${TAILSCALE_AUTHKEY:-}" ]]; then
    echo "  Tailscale:  ${TAILSCALE_IP:-$(tailscale ip -4 2>/dev/null || echo 'pending')}"
    echo ""
fi

if ! has_ssl_certs; then
    echo "============================================================================="
    echo -e "${YELLOW} NEXT STEPS:${NC}"
    echo "============================================================================="
    echo ""
    echo "  1. Place Cloudflare Origin Server certificates:"
    echo "       $SSL_CERT"
    echo "       $SSL_KEY"
    echo ""
    echo "  2. Re-run deployment to enable HTTPS:"
    echo "       deploy_a2a.sh"
    echo ""
fi

echo "  Edit secrets:  sudo nano $INSTALL_DIR/.env"
echo "  Restart:       sudo systemctl restart a2a-gateway"
echo "  Health check:  curl ${PROTO}://$DOMAIN/v1/health"
echo ""
echo "============================================================================="
