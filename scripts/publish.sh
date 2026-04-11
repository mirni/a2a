#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Post-audit publish script
# =============================================================================
#
# Tags an existing release commit on main and pushes the tag, which triggers
# .github/workflows/publish.yml to publish PyPI + npm + Docker packages.
#
# Intended flow:
#
#   implementation → PR → CI → merge to main
#                                  │
#                                  ▼
#                       scripts/release.sh --skip-publish
#                       (bumps versions, deploys, merges to main —
#                        but does NOT create the v<version> tag)
#                                  │
#                                  ▼
#                           External audit runs
#                                  │
#                                  ▼
#                       scripts/publish.sh --version 1.2.7
#                       (creates v1.2.7 tag on the release commit,
#                        publish.yml auto-fires, waits for completion)
#
# Usage:
#   scripts/publish.sh --version <x.y.z> [OPTIONS]
#
# Required:
#   --version <x.y.z>        Version to publish (must match a release commit
#                            already on main). The script finds the commit by
#                            matching its subject against "release: v<version>".
#
# Optional:
#   --sha <commit>           Explicit release commit SHA (skips subject search).
#                            Useful if multiple release commits share a version
#                            or if you're publishing from a non-standard branch.
#   --dry-run                Validate everything and print what would happen,
#                            but don't create/push the tag.
#   --yes                    Skip the interactive confirmation prompt.
#   --wait-timeout <seconds> Max seconds to wait for publish.yml to finish
#                            (default: 1800 = 30 minutes).
#   -h, --help               Show this help message.
#
# Requirements:
#   - gh CLI installed and authenticated (GH_TOKEN or gh auth login)
#   - git with push access to the repository
#   - Tag v<version> does not yet exist (local or remote)
#   - A release commit for v<version> is reachable from main
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Bootstrap: load .env for GH_TOKEN/GITHUB_DEPLOYMENT_TOKEN
# ---------------------------------------------------------------------------

if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

# ---------------------------------------------------------------------------
# Colors and logging (matches release.sh conventions)
# ---------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log()     { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
err()     { echo -e "${RED}[x]${NC} $*" >&2; exit 1; }
info()    { echo -e "${BLUE}[i]${NC} $*"; }
header()  { echo -e "\n${BOLD}═══ $* ═══${NC}"; }

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

VERSION=""
SHA=""
DRY_RUN=false
SKIP_CONFIRM=false
WAIT_TIMEOUT=1800
POLL_INTERVAL=15

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

usage() {
    sed -n '/^# Usage:/,/^# ====/p' "$0" | sed 's/^# \?//'
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)       VERSION="$2";       shift 2 ;;
        --sha)           SHA="$2";           shift 2 ;;
        --dry-run)       DRY_RUN=true;       shift   ;;
        --yes|-y)        SKIP_CONFIRM=true;  shift   ;;
        --wait-timeout)  WAIT_TIMEOUT="$2";  shift 2 ;;
        -h|--help)       usage ;;
        *)               err "Unknown option: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------

[[ -n "$VERSION" ]] || err "Missing required --version <x.y.z>"

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    err "Invalid version format: '$VERSION'. Expected x.y.z (e.g. 1.2.7)"
fi

if [[ "$DRY_RUN" == false ]] && ! command -v gh &>/dev/null; then
    err "gh CLI not found. Install: https://cli.github.com"
fi

TAG="v${VERSION}"

# ---------------------------------------------------------------------------
# Step 1: Ensure tag does not already exist
# ---------------------------------------------------------------------------

header "Step 1: Check tag does not exist"

# Refresh remote refs so we catch a tag pushed from another machine.
git -C "$REPO_ROOT" fetch --tags --quiet

if git -C "$REPO_ROOT" tag -l "$TAG" | grep -q "^${TAG}$"; then
    err "Tag ${TAG} already exists locally. Has this version been published already?
Hint: git tag -d ${TAG} && git fetch --tags   # refresh from origin"
fi

if git -C "$REPO_ROOT" ls-remote --tags origin "refs/tags/${TAG}" | grep -q "${TAG}"; then
    err "Tag ${TAG} already exists on origin. Has this version been published already?"
fi

log "Tag ${TAG} is available"

# ---------------------------------------------------------------------------
# Step 2: Locate the release commit
# ---------------------------------------------------------------------------

header "Step 2: Locate release commit"

if [[ -z "$SHA" ]]; then
    info "Searching main history for 'release: v${VERSION}' commit..."
    # Make sure we have up-to-date main
    git -C "$REPO_ROOT" fetch origin main --quiet
    SHA=$(git -C "$REPO_ROOT" log origin/main \
        --grep="^release: v${VERSION}$" \
        --format="%H" 2>/dev/null | head -1 || true)

    if [[ -z "$SHA" ]]; then
        err "Could not find 'release: v${VERSION}' commit on origin/main.
Options:
  1. Run scripts/release.sh --version ${VERSION} --skip-publish first.
  2. Pass --sha <commit> explicitly if the commit lives elsewhere."
    fi
fi

# Validate SHA exists
if ! git -C "$REPO_ROOT" cat-file -e "$SHA" 2>/dev/null; then
    err "Git commit not found: $SHA"
fi

SHA=$(git -C "$REPO_ROOT" rev-parse "$SHA")
SHA_SHORT="${SHA:0:8}"
SUBJECT=$(git -C "$REPO_ROOT" log --format="%s" -1 "$SHA")

info "Release commit: ${SHA_SHORT} — ${SUBJECT}"

# Confirm the commit is actually reachable from origin/main — otherwise the
# tag will point at something that isn't on the mainline.
if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$SHA" origin/main 2>/dev/null; then
    err "Commit ${SHA_SHORT} is not reachable from origin/main.
Refusing to tag a release on a non-mainline commit. Make sure the release
branch has been merged to main first."
fi

log "Commit ${SHA_SHORT} is on origin/main"

# ---------------------------------------------------------------------------
# Step 3: Verify version markers at that commit match the requested version
# ---------------------------------------------------------------------------

header "Step 3: Verify version markers at ${SHA_SHORT}"

check_file_version() {
    local path="$1" expected="$2" pattern="$3" label="$4"
    local actual
    actual=$(git -C "$REPO_ROOT" show "${SHA}:${path}" 2>/dev/null | \
        grep -m1 -E "$pattern" | sed -E "s/.*${pattern}.*/\\1/" || true)
    if [[ -z "$actual" ]]; then
        warn "${label}: could not extract version from ${path}@${SHA_SHORT}"
        return 0
    fi
    if [[ "$actual" != "$expected" ]]; then
        err "${label} version mismatch at ${SHA_SHORT}: ${path} has '${actual}', expected '${expected}'.
Did you run release.sh for the right version?"
    fi
    log "${label}: ${actual} ✓"
}

# gateway/src/_version.py → __version__ = "x.y.z"
check_file_version \
    "gateway/src/_version.py" \
    "$VERSION" \
    '^__version__ = "([^"]+)"' \
    "gateway/src/_version.py"

# sdk/pyproject.toml → version = "x.y.z"
check_file_version \
    "sdk/pyproject.toml" \
    "$VERSION" \
    '^version = "([^"]+)"' \
    "sdk/pyproject.toml"

# sdk-ts/package.json → "version": "x.y.z"
check_file_version \
    "sdk-ts/package.json" \
    "$VERSION" \
    '"version": "([^"]+)"' \
    "sdk-ts/package.json"

# ---------------------------------------------------------------------------
# Step 4: Confirm and tag
# ---------------------------------------------------------------------------

header "Step 4: Create tag ${TAG}"

echo ""
info "About to create and push tag:"
info "  tag:    ${TAG}"
info "  commit: ${SHA_SHORT}"
info "  branch: origin/main"
info "  trigger: .github/workflows/publish.yml (PyPI + npm + Docker)"
echo ""

if [[ "$DRY_RUN" == true ]]; then
    warn "Dry run — stopping before tag creation."
    info "To publish for real:   scripts/publish.sh --version ${VERSION}"
    exit 0
fi

if [[ "$SKIP_CONFIRM" == false ]]; then
    read -rp "Proceed with publish? [y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        info "Publish cancelled."
        exit 0
    fi
fi

git -C "$REPO_ROOT" tag -a "$TAG" -m "Release ${TAG}" "$SHA"
log "Created tag ${TAG} at ${SHA_SHORT}"

git -C "$REPO_ROOT" push origin "$TAG"
log "Pushed tag ${TAG} to origin"

# ---------------------------------------------------------------------------
# Step 5: Wait for publish.yml to complete
# ---------------------------------------------------------------------------

header "Step 5: Wait for Publish workflow"

info "Waiting for publish.yml run to appear..."

# Give GitHub a moment to register the tag push
sleep 5

RUN_ID=""
for attempt in $(seq 1 12); do
    RUN_ID=$(gh run list \
        --workflow "Publish" \
        --event push \
        --limit 5 \
        --json databaseId,headBranch \
        --jq ".[] | select(.headBranch == \"${TAG}\") | .databaseId" 2>/dev/null | head -1 || echo "")
    if [[ -n "$RUN_ID" ]]; then
        break
    fi
    info "Publish run not registered yet (attempt ${attempt}/12)..."
    sleep 5
done

if [[ -z "$RUN_ID" ]]; then
    warn "Could not locate the Publish workflow run after 60s."
    warn "Tag was pushed successfully — check manually:"
    warn "  gh run list --workflow Publish --limit 5"
    exit 0
fi

info "Publish run ID: ${RUN_ID}"
info "Watch live:     gh run watch ${RUN_ID}"

elapsed=0
publish_passed=false

while (( elapsed < WAIT_TIMEOUT )); do
    run_result=$(gh run view "$RUN_ID" --json status,conclusion \
        --jq '.status + ":" + (.conclusion // "")' 2>/dev/null || echo "unknown:")

    run_status="${run_result%%:*}"
    run_conclusion="${run_result##*:}"

    if [[ "$run_status" == "completed" ]]; then
        if [[ "$run_conclusion" == "success" ]]; then
            publish_passed=true
        fi
        break
    fi

    info "Publish status: ${run_status} (${elapsed}s / ${WAIT_TIMEOUT}s)"
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

# ---------------------------------------------------------------------------
# Step 6: Summary
# ---------------------------------------------------------------------------

header "Publish ${TAG} Complete"
echo ""

if [[ "$publish_passed" == true ]]; then
    log "Version:    ${TAG}"
    log "Commit:     ${SHA_SHORT}"
    log "Publish run: ${RUN_ID}"
    log "PyPI:        https://pypi.org/project/a2a-greenhelix-sdk/${VERSION}/"
    log "npm:         https://www.npmjs.com/package/@greenhelix/sdk/v/${VERSION}"
    log "Docker:      docker pull greenhelix/a2a-gateway:${VERSION}"
    echo ""
    info "Next steps:"
    info "  - Verify PyPI:   pip install a2a-greenhelix-sdk==${VERSION}"
    info "  - Verify npm:    npm view @greenhelix/sdk@${VERSION}"
    info "  - Verify Docker: docker pull greenhelix/a2a-gateway:${VERSION}"
    exit 0
fi

# Not passed
if (( elapsed >= WAIT_TIMEOUT )); then
    warn "Publish workflow timed out after ${WAIT_TIMEOUT}s."
else
    warn "Publish workflow finished with conclusion: ${run_conclusion:-unknown}"
fi

warn "Tag ${TAG} has been pushed. Check the run:"
warn "  gh run view ${RUN_ID}"
warn "  gh run view ${RUN_ID} --log-failed"
exit 1
