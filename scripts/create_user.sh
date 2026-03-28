#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — System user and directory setup
# Creates the a2a service user and all required directories.
# Idempotent: safe to run multiple times.
# =============================================================================

source "$(dirname "${BASH_SOURCE[0]}")/common.bash"
require_root

# ---------------------------------------------------------------------------
# System user
# ---------------------------------------------------------------------------

if ! id "$A2A_USER" &>/dev/null; then
    log "Creating system user '$A2A_USER'..."
    useradd --system --shell /usr/sbin/nologin --home-dir "$INSTALL_DIR" "$A2A_USER"
else
    log "User '$A2A_USER' already exists"
fi

# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

log "Ensuring directories exist..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$DATA_DIR"/{billing,paywall,payments,marketplace,trust,identity,messaging,disputes,events,webhooks}
mkdir -p /var/log/a2a
mkdir -p "$BACKUP_DIR"
mkdir -p "$SSL_DIR"

# ---------------------------------------------------------------------------
# Ownership and permissions
# ---------------------------------------------------------------------------

chown -R "$A2A_USER:$A2A_GROUP" "$DATA_DIR"
chown -R "$A2A_USER:$A2A_GROUP" /var/log/a2a
chmod 750 "$DATA_DIR"

log "User and directories ready"
