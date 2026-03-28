#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Website deployment
# Deploys static website files and configures nginx.
# Skips entirely if A2A_WWW_DOMAIN is not set.
# =============================================================================

source "$(dirname "${BASH_SOURCE[0]}")/common.bash"
require_root

# ---------------------------------------------------------------------------
# Skip if no website domain configured
# ---------------------------------------------------------------------------

if [[ -z "$WWW_DOMAIN" ]]; then
    log "No A2A_WWW_DOMAIN set, skipping website deployment"
    exit 0
fi

# ---------------------------------------------------------------------------
# Deploy static files
# ---------------------------------------------------------------------------

WEBSITE_ROOT="/var/www/${WWW_DOMAIN}"
log "Deploying company website to $WEBSITE_ROOT..."

mkdir -p "$WEBSITE_ROOT"
if [[ -d "$INSTALL_DIR/website" ]]; then
    cp -r "$INSTALL_DIR/website/"* "$WEBSITE_ROOT/"
    chown -R www-data:www-data "$WEBSITE_ROOT"
else
    warn "website/ directory not found in repo, creating placeholder"
    echo "<h1>$WWW_DOMAIN</h1>" > "$WEBSITE_ROOT/index.html"
    chown -R www-data:www-data "$WEBSITE_ROOT"
fi

# ---------------------------------------------------------------------------
# Nginx config (Cloudflare Origin SSL or HTTP-only)
# ---------------------------------------------------------------------------

if has_ssl_certs; then
    log "Cloudflare Origin certificates found — configuring HTTPS for website"
    cat > /etc/nginx/sites-available/website << WEBEOF
# Company website — static files (Cloudflare Full Strict)

server {
    listen 80;
    listen [::]:80;
    server_name $WWW_DOMAIN www.$WWW_DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $WWW_DOMAIN www.$WWW_DOMAIN;

    ssl_certificate     $SSL_CERT;
    ssl_certificate_key $SSL_KEY;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    root $WEBSITE_ROOT;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }

    # Cache static assets
    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
WEBEOF
else
    warn "No Cloudflare Origin certs — configuring HTTP-only for website"
    cat > /etc/nginx/sites-available/website << WEBEOF
# Company website — static files (HTTP-only, no SSL certs yet)
# To enable HTTPS:
#   1. Place Cloudflare Origin certs at $SSL_CERT and $SSL_KEY
#   2. Re-run: deploy_website.sh

server {
    listen 80;
    listen [::]:80;
    server_name $WWW_DOMAIN www.$WWW_DOMAIN;

    root $WEBSITE_ROOT;
    index index.html;

    location / {
        try_files \$uri \$uri/ =404;
    }

    # Cache static assets
    location ~* \.(css|js|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
WEBEOF
fi

enable_nginx_site website
log "Website deployed at ${WWW_DOMAIN}"
