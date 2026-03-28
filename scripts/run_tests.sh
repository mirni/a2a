#!/usr/bin/env bash
# =============================================================================
# Run pytest for a given module with correct PYTHONPATH isolation.
#
# Usage:
#   scripts/run_tests.sh gateway
#   scripts/run_tests.sh products/billing
#   scripts/run_tests.sh sdk
# =============================================================================

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <module-path> [extra pytest args...]"
    echo "  e.g. $0 products/billing"
    exit 1
fi

MODULE="$1"; shift
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$MODULE" in
    gateway|sdk)
        # Top-level modules: run from repo root
        PYTHONPATH="$REPO_ROOT" \
            python -m pytest "$REPO_ROOT/$MODULE/tests/" -x -q --tb=short "$@"
        ;;
    products/*)
        # Product modules: need repo root + product dir on PYTHONPATH
        PYTHONPATH="$REPO_ROOT:$REPO_ROOT/$MODULE" \
            python -m pytest "$REPO_ROOT/$MODULE/tests/" -x -q --tb=short "$@"
        ;;
    *)
        echo "Unknown module: $MODULE"
        exit 1
        ;;
esac
