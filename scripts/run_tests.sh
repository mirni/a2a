#!/usr/bin/env bash
# =============================================================================
# Run pytest for a given module with correct PYTHONPATH isolation.
#
# Usage:
#   scripts/run_tests.sh gateway              # single module
#   scripts/run_tests.sh products/billing     # single product
#   scripts/run_tests.sh sdk                  # SDK tests
#   scripts/run_tests.sh --all                # run ALL modules sequentially
#   scripts/run_tests.sh --all --parallel     # run ALL modules in parallel
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Discover a python that has pytest available
PYTHON="${PYTHON:-python}"
if ! "$PYTHON" -m pytest --version >/dev/null 2>&1; then
    for candidate in python3 python; do
        if "$candidate" -m pytest --version >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done
fi

# ---------------------------------------------------------------------------
# --all mode: run every module
# ---------------------------------------------------------------------------
ALL_MODULES=(
    gateway
    products/shared
    products/billing
    products/paywall
    products/payments
    products/marketplace
    products/trust
    products/identity
    products/messaging
    products/reputation
)

run_one() {
    local module="$1"; shift
    local base_path="${PYTHONPATH:+$PYTHONPATH:}"
    case "$module" in
        gateway|sdk)
            PYTHONPATH="${base_path}$REPO_ROOT" \
                $PYTHON -m pytest "$REPO_ROOT/$module/tests/" -x -q --tb=short "$@"
            ;;
        products/*)
            PYTHONPATH="${base_path}$REPO_ROOT:$REPO_ROOT/$module" \
                $PYTHON -m pytest "$REPO_ROOT/$module/tests/" -x -q --tb=short "$@"
            ;;
        *)
            echo "Unknown module: $module"
            return 1
            ;;
    esac
}

if [[ "${1:-}" == "--all" ]]; then
    shift
    PARALLEL=false
    EXTRA_ARGS=()
    for arg in "$@"; do
        if [[ "$arg" == "--parallel" ]]; then
            PARALLEL=true
        else
            EXTRA_ARGS+=("$arg")
        fi
    done

    PASS=0
    FAIL=0
    FAILED_MODULES=()

    if $PARALLEL; then
        echo "Running all modules in parallel..."
        PIDS=()
        LOGS=()
        for mod in "${ALL_MODULES[@]}"; do
            LOG=$(mktemp)
            LOGS+=("$LOG")
            (run_one "$mod" "${EXTRA_ARGS[@]}" > "$LOG" 2>&1) &
            PIDS+=($!)
        done

        for i in "${!PIDS[@]}"; do
            mod="${ALL_MODULES[$i]}"
            if wait "${PIDS[$i]}"; then
                PASS=$((PASS + 1))
                printf '  \033[0;32mPASS\033[0m  %s\n' "$mod"
            else
                FAIL=$((FAIL + 1))
                FAILED_MODULES+=("$mod")
                printf '  \033[0;31mFAIL\033[0m  %s\n' "$mod"
            fi
            # Show last line (summary) from log
            tail -1 "${LOGS[$i]}" 2>/dev/null || true
            rm -f "${LOGS[$i]}"
        done
    else
        for mod in "${ALL_MODULES[@]}"; do
            echo ""
            echo "=== $mod ==="
            if run_one "$mod" "${EXTRA_ARGS[@]}"; then
                PASS=$((PASS + 1))
            else
                FAIL=$((FAIL + 1))
                FAILED_MODULES+=("$mod")
            fi
        done
    fi

    echo ""
    echo "======================================"
    TOTAL=$((PASS + FAIL))
    printf 'Modules: %d | \033[0;32mPass: %d\033[0m | \033[0;31mFail: %d\033[0m\n' "$TOTAL" "$PASS" "$FAIL"

    if [[ $FAIL -gt 0 ]]; then
        echo "Failed: ${FAILED_MODULES[*]}"
        exit 1
    fi
    exit 0
fi

# ---------------------------------------------------------------------------
# Single-module mode
# ---------------------------------------------------------------------------
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <module-path> [extra pytest args...]"
    echo "       $0 --all [--parallel] [extra pytest args...]"
    echo ""
    echo "Modules: ${ALL_MODULES[*]}"
    exit 1
fi

MODULE="$1"; shift
run_one "$MODULE" "$@"
