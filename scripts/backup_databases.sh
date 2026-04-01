#!/bin/bash
# =============================================================================
# A2A Commerce Platform — Database Backup Script
#
# Backs up all SQLite databases with integrity verification and retention.
#
# Usage:
#   ./scripts/backup_databases.sh
#
# Environment:
#   A2A_DATA_DIR   Directory containing .db files (default: /var/lib/a2a)
#   RETENTION_DAYS  Days to keep backups (default: 30)
# =============================================================================

set -euo pipefail

DATA_DIR="${A2A_DATA_DIR:-/var/lib/a2a}"
BACKUP_DIR="/var/backups/a2a/$(date +%Y%m%d-%H%M%S)"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
LOGFILE="/var/log/a2a/backup.log"

log() { echo "$(date -Iseconds) $*" | tee -a "$LOGFILE"; }

mkdir -p "$BACKUP_DIR"
FAIL=0

for db in "$DATA_DIR"/*.db; do
    [ -f "$db" ] || continue
    BASENAME=$(basename "$db")
    DEST="$BACKUP_DIR/$BASENAME"
    if sqlite3 "$db" ".backup '$DEST'" 2>>"$LOGFILE"; then
        # Verify backup integrity
        if sqlite3 "$DEST" "PRAGMA integrity_check;" | grep -q "^ok$"; then
            SIZE=$(stat -c%s "$DEST")
            log "OK: $BASENAME → $DEST ($SIZE bytes)"
        else
            log "FAIL: $BASENAME integrity check failed"
            FAIL=1
        fi
    else
        log "FAIL: $BASENAME backup failed"
        FAIL=1
    fi
done

# Retention: remove backups older than $RETENTION_DAYS days
find /var/backups/a2a -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true
log "Retention cleanup done (keeping $RETENTION_DAYS days)"

exit $FAIL
