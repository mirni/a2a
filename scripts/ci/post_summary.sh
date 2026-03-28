#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Post a markdown report to GitHub Actions job summary
#
# Usage:
#   scripts/ci/post_summary.sh <report_file> [heading]
# =============================================================================

set -uo pipefail  # no -e: this script must never fail

REPORT_FILE="${1:-}"
HEADING="${2:-}"

if [[ -z "$REPORT_FILE" ]]; then
    echo "Usage: $0 <report_file> [heading]" >&2
    exit 0
fi

if [[ ! -f "$REPORT_FILE" ]]; then
    echo "Report file not found: $REPORT_FILE" >&2
    exit 0
fi

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    if [[ -n "$HEADING" ]]; then
        echo "## $HEADING" >> "$GITHUB_STEP_SUMMARY"
    fi
    cat "$REPORT_FILE" >> "$GITHUB_STEP_SUMMARY"
else
    if [[ -n "$HEADING" ]]; then
        echo "## $HEADING"
    fi
    cat "$REPORT_FILE"
fi
