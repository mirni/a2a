#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Deploy a .deb package to a remote server.
#
# This wrapper delegates to scripts/deploy.sh (remote .deb deployment).
# For full server provisioning (from-scratch setup), use scripts/deploy_a2a.sh.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/scripts/deploy.sh" "$@"
