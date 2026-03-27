#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Automated Deployment Script
# Target: Ubuntu 24.04 LTS (clean machine)
#
# Usage (manual):
#   chmod +x deploy.sh
#   sudo ./deploy.sh                                  # without Tailscale
#   sudo TAILSCALE_AUTHKEY=tskey-auth-... ./deploy.sh  # with Tailscale SSH
#
# Usage (Hetzner cloud-init):
#   Paste this script into the "Cloud config" field when creating a server,
#   or pass via API:
#     hcloud server create --name a2a --type cx22 --image ubuntu-24.04 \
#       --user-data-from-file deploy.sh
#   Pass secrets via a wrapper (see below) — do NOT embed them in user-data.
#
# Cloud-init notes:
#   - Runs as root on first boot only (Stage 5 / final)
#   - Logs: /var/log/cloud-init-output.log + /var/log/a2a-deploy.log
#   - Completion signal: /var/log/a2a-deploy-done (touch on success)
#   - Hetzner marks server "running" BEFORE this finishes
#   - To wait: ssh root@IP "cloud-init status --wait"
#
# What this does:
#   1. Installs system deps (Python 3.12, pip, git, nginx, certbot, sqlite3)
#   2. Creates a2a system user and directory structure
#   3. Clones the repo and installs Python dependencies
#   4. Creates systemd service for the gateway
#   5. Configures nginx reverse proxy with HTTPS (Let's Encrypt)
#   6. Installs Tailscale (if TAILSCALE_AUTHKEY set) — SSH via WireGuard mesh
#   7. Sets up firewall (ufw) — SSH restricted to Tailscale if enabled
#   8. Creates initial admin API key
#   9. Prints final instructions for secrets and DNS
#
# After running, you MUST:
#   - Point your domain DNS to this server's IP
#   - Run: sudo certbot --nginx -d your-domain.com
#   - Edit /opt/a2a/.env with your secrets (Stripe, GitHub, etc.)
#   - Restart: sudo systemctl restart a2a-gateway
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Cloud-init compatibility: logging, environment, apt lock handling
# ---------------------------------------------------------------------------

# Log everything to file (cloud-init also captures stdout, but this persists)
exec > >(tee -a /var/log/a2a-deploy.log) 2>&1
echo "=== deploy.sh started at $(date -u) ==="

# Ensure a sane environment (cloud-init runs with minimal env)
export HOME="${HOME:-/root}"
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"

# Trap: log failures with line number
trap 'echo "FAILED at line $LINENO (exit code $?)" | tee -a /var/log/a2a-deploy.log' ERR

# Wait for any apt/dpkg locks (cloud-init or unattended-upgrades may hold them)
_wait_for_apt() {
    local tries=0
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
          fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
        if (( tries++ > 60 )); then
            echo "ERROR: apt lock held for >5 minutes, aborting"
            return 1
        fi
        echo "Waiting for apt lock (attempt $tries)..."
        sleep 5
    done
}

# Safe apt wrapper: waits for locks, forces non-interactive config
_apt_get() {
    _wait_for_apt
    apt-get -o DPkg::Lock::Timeout=60 \
            -o Dpkg::Options::="--force-confdef" \
            -o Dpkg::Options::="--force-confold" \
            "$@"
}

# ---------------------------------------------------------------------------
# Configuration — change these before running
# ---------------------------------------------------------------------------

DOMAIN="${A2A_DOMAIN:-a2a.example.com}"
REPO_URL="${A2A_REPO_URL:-https://github.com/YOUR_ORG/a2a-commerce.git}"
BRANCH="${A2A_BRANCH:-main}"
INSTALL_DIR="/opt/a2a"
DATA_DIR="/var/lib/a2a"
A2A_USER="a2a"
A2A_GROUP="a2a"
PORT=8000

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[x]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (sudo ./deploy.sh)"
fi

log "Starting A2A Commerce Platform deployment on $(lsb_release -ds 2>/dev/null || echo 'Ubuntu')"

# ---------------------------------------------------------------------------
# Step 1: System packages
# ---------------------------------------------------------------------------

log "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
_apt_get update -qq
_apt_get upgrade -y -qq

log "Installing Python 3.12, nginx, certbot, sqlite3, ufw..."
_apt_get install -y -qq \
    python3.12 python3.12-venv python3.12-dev python3-pip \
    nginx certbot python3-certbot-nginx \
    sqlite3 git curl ufw

# ---------------------------------------------------------------------------
# Step 2: Create system user and directories
# ---------------------------------------------------------------------------

log "Creating system user '$A2A_USER'..."
if ! id "$A2A_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$A2A_USER"
fi

log "Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DATA_DIR"/{billing,paywall,payments,marketplace,trust,identity,messaging,disputes,events,webhooks}
mkdir -p /var/log/a2a

# ---------------------------------------------------------------------------
# Step 3: Clone repository and install dependencies
# ---------------------------------------------------------------------------

if [[ -d "$INSTALL_DIR/.git" ]]; then
    log "Updating existing repository..."
    cd "$INSTALL_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull origin "$BRANCH"
else
    log "Cloning repository..."
    git clone --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

log "Creating Python virtual environment..."
python3.12 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

log "Installing Python dependencies..."
pip install --upgrade pip wheel setuptools -q
pip install \
    starlette'>=0.37' \
    uvicorn'>=0.29' \
    httpx'>=0.27' \
    aiosqlite'>=0.20' \
    pydantic'>=2.0' \
    cryptography'>=42.0' \
    -q

log "Installing SDK in editable mode..."
pip install -e "$INSTALL_DIR/sdk" -q 2>/dev/null || pip install "$INSTALL_DIR/sdk" -q

deactivate

# ---------------------------------------------------------------------------
# Step 4: Create .env file (secrets placeholder)
# ---------------------------------------------------------------------------

ENV_FILE="$INSTALL_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    log "Creating .env from template..."
    cat > "$ENV_FILE" << 'ENVEOF'
# =============================================================================
# A2A Commerce Platform — Production Environment
# =============================================================================
# IMPORTANT: Fill in real values for all REQUIRED fields below.
# This file contains secrets — never commit it to version control.
# =============================================================================

# --- Server ---
HOST=127.0.0.1
PORT=8000

# --- Data directory (SQLite databases stored here) ---
A2A_DATA_DIR=/var/lib/a2a

# --- Database DSNs (SQLite for single-server, PostgreSQL for scale) ---
BILLING_DSN=sqlite:////var/lib/a2a/billing.db
PAYWALL_DSN=sqlite:////var/lib/a2a/paywall.db
PAYMENTS_DSN=sqlite:////var/lib/a2a/payments.db
MARKETPLACE_DSN=sqlite:////var/lib/a2a/marketplace.db
TRUST_DSN=sqlite:////var/lib/a2a/trust.db
EVENT_BUS_DSN=sqlite:////var/lib/a2a/events.db
WEBHOOK_DSN=sqlite:////var/lib/a2a/webhooks.db
IDENTITY_DSN=sqlite:////var/lib/a2a/identity.db
MESSAGING_DSN=sqlite:////var/lib/a2a/messaging.db
DISPUTE_DSN=sqlite:////var/lib/a2a/disputes.db

# --- Connector API Keys (fill in your real keys) ---
# REQUIRED if using Stripe connector:
# STRIPE_API_KEY=sk_live_...
#
# REQUIRED if using GitHub connector:
# GITHUB_TOKEN=ghp_...
#
# REQUIRED if using PostgreSQL connector:
# PG_HOST=localhost
# PG_PORT=5432
# PG_DATABASE=mydb
# PG_USER=myuser
# PG_PASSWORD=mypassword

# --- Logging ---
LOG_LEVEL=INFO
ENVEOF
    chmod 600 "$ENV_FILE"
    log ".env created at $ENV_FILE — edit it with your secrets"
else
    warn ".env already exists, not overwriting"
fi

# ---------------------------------------------------------------------------
# Step 5: Set ownership and permissions
# ---------------------------------------------------------------------------

log "Setting file permissions..."
chown -R "$A2A_USER:$A2A_GROUP" "$INSTALL_DIR"
chown -R "$A2A_USER:$A2A_GROUP" "$DATA_DIR"
chown -R "$A2A_USER:$A2A_GROUP" /var/log/a2a
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------------------
# Step 6: Create systemd service
# ---------------------------------------------------------------------------

log "Creating systemd service..."
cat > /etc/systemd/system/a2a-gateway.service << SVCEOF
[Unit]
Description=A2A Commerce Gateway
After=network.target
Wants=network-online.target

[Service]
Type=exec
User=$A2A_USER
Group=$A2A_GROUP
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=$INSTALL_DIR/venv/bin/python -m uvicorn gateway.main:app \\
    --host 127.0.0.1 \\
    --port $PORT \\
    --workers 2 \\
    --log-level info \\
    --access-log
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$DATA_DIR /var/log/a2a
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable a2a-gateway

# ---------------------------------------------------------------------------
# Step 7: Configure nginx reverse proxy
# ---------------------------------------------------------------------------

log "Configuring nginx..."
cat > /etc/nginx/sites-available/a2a << NGXEOF
# A2A Commerce Gateway — nginx reverse proxy
# After DNS is pointed here, run: sudo certbot --nginx -d $DOMAIN

upstream a2a_backend {
    server 127.0.0.1:$PORT;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://a2a_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";

        # Pass correlation ID through
        proxy_set_header X-Request-ID \$request_id;

        # Timeouts
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 10s;

        # Rate limiting (nginx layer — defense in depth)
        limit_req zone=a2a_limit burst=50 nodelay;
    }

    # Health check (no rate limit)
    location /v1/health {
        proxy_pass http://a2a_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
    }
}
NGXEOF

# Add rate limit zone to nginx.conf if not present
if ! grep -q 'a2a_limit' /etc/nginx/nginx.conf; then
    sed -i '/http {/a\    limit_req_zone \$binary_remote_addr zone=a2a_limit:10m rate=30r/s;' \
        /etc/nginx/nginx.conf
fi

# Enable site
ln -sf /etc/nginx/sites-available/a2a /etc/nginx/sites-enabled/a2a
rm -f /etc/nginx/sites-enabled/default

nginx -t && systemctl reload nginx

# ---------------------------------------------------------------------------
# Step 8a: Install and configure Tailscale
# ---------------------------------------------------------------------------

TAILSCALE_AUTHKEY="${TAILSCALE_AUTHKEY:-}"

# Security: if running via cloud-init, TAILSCALE_AUTHKEY should be passed as
# an env var from a wrapper script, NOT embedded in user-data (which is readable
# from the VM metadata endpoint by any process). Example wrapper:
#
#   #!/bin/bash
#   export TAILSCALE_AUTHKEY="tskey-auth-..."
#   export A2A_DOMAIN="api.greenhelix.net"
#   curl -fsSL https://raw.githubusercontent.com/you/repo/main/deploy.sh | bash
#
# Or set it via Hetzner's metadata labels + a small bootstrap script.

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    log "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh

    log "Starting Tailscale with SSH enabled..."
    tailscale up --authkey="$TAILSCALE_AUTHKEY" --ssh --hostname="a2a-gateway"

    TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "pending")
    log "Tailscale connected. IP: $TAILSCALE_IP"
    log "Tailscale SSH enabled — you can now SSH via Tailscale without keys."
else
    warn "TAILSCALE_AUTHKEY not set — skipping Tailscale setup."
    warn "SSH will remain open on the public interface (key-auth only)."
    warn ""
    warn "To enable Tailscale later:"
    warn "  1. Get an auth key from https://login.tailscale.com/admin/settings/keys"
    warn "  2. Run: curl -fsSL https://tailscale.com/install.sh | sh"
    warn "  3. Run: tailscale up --authkey=tskey-auth-... --ssh --hostname=a2a-gateway"
    warn "  4. Update UFW: ufw delete allow ssh && ufw allow from 100.64.0.0/10 to any port 22"
fi

# ---------------------------------------------------------------------------
# Step 8b: Configure firewall
# ---------------------------------------------------------------------------

log "Configuring firewall..."
ufw --force reset >/dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    # SSH only via Tailscale (100.64.0.0/10 is Tailscale's CGNAT range)
    ufw allow from 100.64.0.0/10 to any port 22
    # WireGuard direct connections (improves latency vs relay)
    ufw allow 41641/udp
    # Emergency fallback: SSH on port 2222 with key-auth + fail2ban
    ufw allow 2222/tcp
    log "SSH restricted to Tailscale network. Emergency fallback on port 2222."
else
    ufw allow ssh
fi

ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ---------------------------------------------------------------------------
# Step 8c: Configure emergency SSH fallback (port 2222)
# ---------------------------------------------------------------------------

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    log "Configuring emergency SSH fallback on port 2222..."

    # Add port 2222 listener to sshd_config if not present
    if ! grep -q "^Port 2222" /etc/ssh/sshd_config; then
        # Keep port 22 (for Tailscale SSH) and add 2222 as fallback
        if grep -q "^Port " /etc/ssh/sshd_config; then
            sed -i '/^Port /a Port 2222' /etc/ssh/sshd_config
        else
            echo "Port 22" >> /etc/ssh/sshd_config
            echo "Port 2222" >> /etc/ssh/sshd_config
        fi
    fi

    # Harden: disable password auth (key-only)
    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sed -i 's/^#\?PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config

    # Install fail2ban for the fallback port
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
    log "fail2ban active on ports 22,2222 (3 strikes = 1h ban)."
fi

# ---------------------------------------------------------------------------
# Step 9: Create initial admin API key
# ---------------------------------------------------------------------------

log "Creating initial admin API key..."
# Create admin wallet and pro key via direct bootstrap (service not running yet)
ADMIN_KEY=$(cd "$INSTALL_DIR" && "$INSTALL_DIR/venv/bin/python" - << 'PYEOF'
import asyncio, sys, os
sys.path.insert(0, "/opt/a2a")
os.environ.setdefault("BILLING_DSN", "sqlite:////var/lib/a2a/billing.db")
os.environ.setdefault("PAYWALL_DSN", "sqlite:////var/lib/a2a/paywall.db")
os.environ.setdefault("PAYMENTS_DSN", "sqlite:////var/lib/a2a/payments.db")
os.environ.setdefault("MARKETPLACE_DSN", "sqlite:////var/lib/a2a/marketplace.db")
os.environ.setdefault("TRUST_DSN", "sqlite:////var/lib/a2a/trust.db")
os.environ.setdefault("EVENT_BUS_DSN", "sqlite:////var/lib/a2a/events.db")
os.environ.setdefault("IDENTITY_DSN", "sqlite:////var/lib/a2a/identity.db")

async def main():
    import gateway.src.bootstrap
    from gateway.src.lifespan import lifespan
    from gateway.src.app import create_app

    app = create_app()
    ctx_mgr = lifespan(app)
    await ctx_mgr.__aenter__()
    ctx = app.state.ctx

    await ctx.tracker.wallet.create("admin", initial_balance=100000.0)
    key_info = await ctx.key_manager.create_key("admin", tier="pro")

    await ctx_mgr.__aexit__(None, None, None)
    print(key_info["key"])

asyncio.run(main())
PYEOF
) 2>/dev/null || ADMIN_KEY="(failed — create manually after fixing .env)"

log "Starting gateway service..."
systemctl start a2a-gateway
sleep 2

# ---------------------------------------------------------------------------
# Step 10: Create backup cron job
# ---------------------------------------------------------------------------

log "Setting up daily database backup..."
mkdir -p /var/backups/a2a

cat > /etc/cron.daily/a2a-backup << 'CRONEOF'
#!/bin/bash
# Daily backup of A2A SQLite databases
BACKUP_DIR="/var/backups/a2a/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"
for db in /var/lib/a2a/*.db; do
    [ -f "$db" ] && sqlite3 "$db" ".backup '$BACKUP_DIR/$(basename $db)'"
done
# Keep 30 days of backups
find /var/backups/a2a -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
CRONEOF
chmod +x /etc/cron.daily/a2a-backup

# ---------------------------------------------------------------------------
# Done — signal completion (for cloud-init monitoring)
# ---------------------------------------------------------------------------

echo "=== deploy.sh finished at $(date -u) ==="
touch /var/log/a2a-deploy-done

echo ""
echo "============================================================================="
echo -e "${GREEN} A2A Commerce Platform — Deployment Complete${NC}"
echo "============================================================================="
echo ""
echo "  Gateway:    http://$DOMAIN (HTTP — HTTPS after certbot)"
echo "  Data dir:   $DATA_DIR"
echo "  Logs:       journalctl -u a2a-gateway -f"
echo "  Config:     $ENV_FILE"
echo ""
echo "  Admin key:  $ADMIN_KEY"
echo ""

if [[ -n "$TAILSCALE_AUTHKEY" ]]; then
    echo "============================================================================="
    echo -e "${GREEN} Tailscale SSH Access:${NC}"
    echo "============================================================================="
    echo ""
    echo "  Tailscale IP:  ${TAILSCALE_IP:-$(tailscale ip -4 2>/dev/null || echo 'pending')}"
    echo "  SSH via:       ssh $(tailscale status --self --json 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("Self",{}).get("DNSName","a2a-gateway").rstrip("."))' 2>/dev/null || echo 'a2a-gateway')"
    echo ""
    echo "  Port 22: Tailscale network only (100.64.0.0/10)"
    echo "  Port 2222: Emergency fallback (key-auth + fail2ban)"
    echo "  fail2ban: 3 failed attempts = 1 hour ban"
    echo ""
    echo "  To add your laptop: install Tailscale, join same tailnet."
    echo "  Admin panel: https://login.tailscale.com/admin/machines"
    echo ""
fi

echo "============================================================================="
echo -e "${YELLOW} REQUIRED NEXT STEPS:${NC}"
echo "============================================================================="
echo ""
echo "  1. POINT DNS: Create an A record for $DOMAIN -> $(curl -s4 ifconfig.me 2>/dev/null || echo '<this-server-ip>')"
echo ""
echo "  2. ENABLE HTTPS (after DNS propagates):"
echo "     sudo certbot --nginx -d $DOMAIN"
echo ""
echo "  3. CONFIGURE SECRETS:"
echo "     sudo nano $ENV_FILE"
echo ""
echo "     Fill in any connector API keys you need:"
echo "       STRIPE_API_KEY=sk_live_...     (for payment processing)"
echo "       GITHUB_TOKEN=ghp_...           (for GitHub connector)"
echo "       PG_HOST / PG_PASSWORD / ...    (for PostgreSQL connector)"
echo ""
echo "  4. RESTART after editing .env:"
echo "     sudo systemctl restart a2a-gateway"
echo ""
echo "  5. VERIFY:"
echo "     curl https://$DOMAIN/v1/health"
echo "     curl https://$DOMAIN/v1/pricing"
echo "     curl https://$DOMAIN/v1/openapi.json"
echo ""
echo "  6. SAVE YOUR ADMIN KEY somewhere safe:"
echo "     $ADMIN_KEY"
echo "     This is a pro-tier key with 100k credits."
echo "     Use it as: curl -H 'Authorization: Bearer $ADMIN_KEY' ..."
echo ""
echo "============================================================================="
echo -e "${GREEN} Service Management:${NC}"
echo "============================================================================="
echo ""
echo "  Start:      sudo systemctl start a2a-gateway"
echo "  Stop:       sudo systemctl stop a2a-gateway"
echo "  Restart:    sudo systemctl restart a2a-gateway"
echo "  Status:     sudo systemctl status a2a-gateway"
echo "  Logs:       journalctl -u a2a-gateway -f"
echo "  Metrics:    curl http://localhost:$PORT/v1/metrics"
echo ""
echo "============================================================================="
echo -e "${GREEN} For agents to connect (Python SDK):${NC}"
echo "============================================================================="
echo ""
echo "  pip install httpx"
echo "  # Then in your agent code:"
echo "  from a2a_client import A2AClient"
echo "  async with A2AClient('https://$DOMAIN', api_key='a2a_pro_...') as client:"
echo "      health = await client.health()"
echo "      balance = await client.get_balance('my-agent')"
echo ""
echo "============================================================================="
