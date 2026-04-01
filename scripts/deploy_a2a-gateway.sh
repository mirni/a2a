#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Gateway deployment
# Handles: venv, Python deps, .env, permissions, shell config, systemd,
#          nginx (Cloudflare Origin SSL or HTTP-only), admin key, backup cron.
# Idempotent: safe to run on install and upgrade.
# =============================================================================

source "$(dirname "${BASH_SOURCE[0]}")/common.bash"
require_root

# ---------------------------------------------------------------------------
# Step 1: Python virtual environment and dependencies
# ---------------------------------------------------------------------------

log "Setting up Python virtual environment..."
python3.12 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip wheel setuptools -q

log "Installing Python dependencies..."
"$INSTALL_DIR/venv/bin/pip" install \
    'starlette>=0.37' \
    'uvicorn>=0.29' \
    'httpx>=0.27' \
    'aiosqlite>=0.20' \
    'pydantic>=2.0' \
    'cryptography>=42.0' \
    -q

log "Installing SDK in editable mode..."
"$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR/sdk" -q 2>/dev/null \
    || "$INSTALL_DIR/venv/bin/pip" install "$INSTALL_DIR/sdk" -q

# ---------------------------------------------------------------------------
# Step 2: .env file (never overwrite existing)
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
    warn ".env already exists at $ENV_FILE, not overwriting"
fi

# ---------------------------------------------------------------------------
# Step 3: Ownership and permissions
# ---------------------------------------------------------------------------

log "Setting file permissions..."
chown -R "$A2A_USER:$A2A_GROUP" "$INSTALL_DIR"
chown -R "$A2A_USER:$A2A_GROUP" "$DATA_DIR"
chown -R "$A2A_USER:$A2A_GROUP" /var/log/a2a
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------------------
# Step 4: Shell config for root
# ---------------------------------------------------------------------------

BASHRC_SRC="$INSTALL_DIR/server/.bashrc"
BASHRC_DST="/root/.bashrc"
BASHRC_MARKER="# --- A2A SERVER CONFIG ---"

if [[ -f "$BASHRC_SRC" ]]; then
    log "Installing server shell config to $BASHRC_DST..."
    if [[ -f "$BASHRC_DST" ]] && grep -qF "$BASHRC_MARKER" "$BASHRC_DST"; then
        # Replace existing managed block
        sed -i "/$BASHRC_MARKER BEGIN/,/$BASHRC_MARKER END/d" "$BASHRC_DST"
    fi
    {
        echo "$BASHRC_MARKER BEGIN"
        cat "$BASHRC_SRC"
        echo "$BASHRC_MARKER END"
    } >> "$BASHRC_DST"
    log "Shell config installed (source ~/.bashrc to activate)"
else
    warn "server/.bashrc not found in repo, skipping shell config"
fi

# ---------------------------------------------------------------------------
# Step 5: Systemd service
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
    --workers 1 \\
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
# Step 6: Nginx reverse proxy (Cloudflare Origin SSL or HTTP-only)
# ---------------------------------------------------------------------------

log "Configuring nginx for gateway..."

# Remove default site
rm -f /etc/nginx/sites-enabled/default

# Harden nginx configuration
ensure_nginx_rate_limit
ensure_nginx_timeouts
ensure_nginx_server_tokens_off

if has_ssl_certs; then
    log "Cloudflare Origin certificates found — configuring HTTPS"
    cat > /etc/nginx/sites-available/a2a << NGXEOF
# A2A Commerce Gateway — nginx reverse proxy (Cloudflare Full Strict)

upstream a2a_backend {
    server 127.0.0.1:$PORT;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate     $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://a2a_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_set_header X-Request-ID \$request_id;

        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 10s;

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
else
    warn "No Cloudflare Origin certs found at $SSL_DIR"
    warn "Configuring HTTP-only — place certs and re-run to enable HTTPS"
    cat > /etc/nginx/sites-available/a2a << NGXEOF
# A2A Commerce Gateway — nginx reverse proxy (HTTP-only, no SSL certs yet)
# To enable HTTPS:
#   1. Place Cloudflare Origin certs at $SSL_CERT and $SSL_KEY
#   2. Re-run: deploy_a2a-gateway.sh

upstream a2a_backend {
    server 127.0.0.1:$PORT;
    keepalive 32;
}

server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    location / {
        proxy_pass http://a2a_backend;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_set_header X-Request-ID \$request_id;

        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
        proxy_send_timeout 10s;

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
fi

enable_nginx_site a2a

# ---------------------------------------------------------------------------
# Step 7: Admin API key (first install only)
# ---------------------------------------------------------------------------

# Only create admin key if billing DB doesn't exist yet (first install)
if [[ ! -f "$DATA_DIR/billing.db" ]]; then
    log "Creating initial admin API key..."
    ADMIN_KEY=$("$INSTALL_DIR/venv/bin/python" - << 'PYEOF'
import asyncio, sys, os
sys.path.insert(0, "/opt/a2a")
os.environ.setdefault("BILLING_DSN", "sqlite:////var/lib/a2a/billing.db")
os.environ.setdefault("PAYWALL_DSN", "sqlite:////var/lib/a2a/paywall.db")
os.environ.setdefault("PAYMENTS_DSN", "sqlite:////var/lib/a2a/payments.db")
os.environ.setdefault("MARKETPLACE_DSN", "sqlite:////var/lib/a2a/marketplace.db")
os.environ.setdefault("TRUST_DSN", "sqlite:////var/lib/a2a/trust.db")
os.environ.setdefault("EVENT_BUS_DSN", "sqlite:////var/lib/a2a/events.db")
os.environ.setdefault("IDENTITY_DSN", "sqlite:////var/lib/a2a/identity.db")
os.environ.setdefault("WEBHOOK_DSN", "sqlite:////var/lib/a2a/webhooks.db")
os.environ.setdefault("MESSAGING_DSN", "sqlite:////var/lib/a2a/messaging.db")
os.environ.setdefault("DISPUTE_DSN", "sqlite:////var/lib/a2a/disputes.db")

async def main():
    from gateway.src.lifespan import lifespan
    from gateway.src.app import create_app

    app = create_app()
    ctx_mgr = lifespan(app)
    await ctx_mgr.__aenter__()
    ctx = app.state.ctx

    await ctx.tracker.wallet.create("admin", initial_balance=100000.0)
    key_info = await ctx.key_manager.create_key("admin", tier="admin", scopes=["read", "write", "admin"])

    await ctx_mgr.__aexit__(None, None, None)
    print(key_info["key"])

asyncio.run(main())
PYEOF
    ) 2>/dev/null || ADMIN_KEY="(failed — create manually after fixing .env)"

    # Export for summary display
    export A2A_ADMIN_KEY="$ADMIN_KEY"
else
    log "Existing billing.db found — skipping admin key creation"
fi

# ---------------------------------------------------------------------------
# Step 8: Start/restart gateway service
# ---------------------------------------------------------------------------

log "Starting gateway service..."
systemctl restart a2a-gateway
sleep 2

# ---------------------------------------------------------------------------
# Step 9: Daily backup cron
# ---------------------------------------------------------------------------

log "Setting up daily database backup..."
mkdir -p "$BACKUP_DIR"

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

log "Gateway deployment complete"
