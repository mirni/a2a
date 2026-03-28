#!/usr/bin/env bash
# =============================================================================
# DEPRECATED: Use 'sudo apt install a2a-server' or run deploy_a2a.sh directly.
# This wrapper exists for backward compatibility.
#
# All deployment logic has been refactored into modular scripts:
#   scripts/common.bash          — Shared functions and config
#   scripts/create_user.sh       — System user and directories
#   scripts/deploy_a2a-gateway.sh — Gateway: venv, deps, systemd, nginx
#   scripts/deploy_website.sh    — Static website deployment
#   scripts/deploy_a2a.sh        — Main orchestrator (replaces this file)
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/scripts/deploy_a2a.sh" "$@"
