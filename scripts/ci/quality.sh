#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Local quality checks
# =============================================================================
# Runs the same checks as the CI quality job. Use before opening a PR.
#
# Usage:
#   scripts/ci/quality.sh
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== Ruff lint ==="
ruff check .

echo "=== Ruff format ==="
ruff format --check .

echo "=== Mypy ==="
mypy $(find gateway/src products/*/src products/connectors/*/src -maxdepth 0 -type d 2>/dev/null | sort)

echo "=== Bandit ==="
bandit -r gateway/src products/ -ll -q --skip B101,B108,B608 --exclude '*/tests/*'

echo "All quality checks passed."
