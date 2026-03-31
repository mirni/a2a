#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Install Python dependencies for CI
#
# Usage:
#   scripts/ci/install_deps.sh              # runtime deps only
#   scripts/ci/install_deps.sh --with-test  # runtime + test deps
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

RUNTIME_DEPS=(
    "starlette>=0.37"
    "uvicorn>=0.29"
    "httpx>=0.27"
    "aiosqlite>=0.20"
    "pydantic>=2.0"
    "cryptography>=42.0"
)

TEST_DEPS=(
    "pytest>=8.0"
    "pytest-asyncio>=0.23"
    "pytest-cov>=5.0"
    "jsonschema>=4.0"
)

WITH_TEST=0
for arg in "$@"; do
    case "$arg" in
        --with-test) WITH_TEST=1 ;;
        *) echo "Unknown flag: $arg" >&2; exit 1 ;;
    esac
done

python -m pip install --upgrade pip

DEPS=("${RUNTIME_DEPS[@]}")
if [[ "$WITH_TEST" -eq 1 ]]; then
    DEPS+=("${TEST_DEPS[@]}")
fi

pip install "${DEPS[@]}"

pip install -e "$REPO_ROOT/sdk/" || pip install "$REPO_ROOT/sdk/"
