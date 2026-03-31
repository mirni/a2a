#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — One-command release script
# =============================================================================
#
# Creates a release branch, bumps versions, generates changelog + release notes,
# runs CI, and triggers production deployment.
#
# Usage:
#   ./scripts/release.sh --sha <commit> --version <x.y.z> --component <comp>
#
# Examples:
#   # Release gateway from current HEAD
#   ./scripts/release.sh --version 1.0.0 --component a2a-gateway
#
#   # Release everything from a specific commit
#   ./scripts/release.sh --sha abc1234 --version 1.0.0 --component all
#
#   # Release only the website
#   ./scripts/release.sh --version 1.0.0 --component a2a-website
#
#   # Dry-run (no push, no deploy)
#   ./scripts/release.sh --version 1.0.0 --component all --dry-run
#
# Components:
#   a2a-gateway   Deploy only the API gateway
#   a2a-website   Deploy only the static website
#   all           Deploy both gateway and website
#
# Requirements:
#   - gh CLI (GitHub CLI) installed and authenticated
#   - git with push access to the repository
#   - Clean working tree (no uncommitted changes)
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------------------------------------------------------------------------
# Colors and logging
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

SHA=""
VERSION=""
COMPONENT=""
DRY_RUN=false
CI_TIMEOUT=600      # Max seconds to wait for CI
DEPLOY_TIMEOUT=600  # Max seconds to wait for deploy
POLL_INTERVAL=15    # Seconds between status checks
SKIP_CI=false
SKIP_DEPLOY=false

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------

usage() {
    cat << 'USAGE'
Usage: ./scripts/release.sh [OPTIONS]

Required:
  --version <x.y.z>       Release version number
  --component <name>       Component to deploy: a2a-gateway, a2a-website, all

Optional:
  --sha <commit>           Git commit SHA to release (default: HEAD)
  --dry-run                Prepare release branch but don't push or deploy
  --skip-ci                Skip waiting for CI (deploy immediately)
  --skip-deploy            Create release branch but don't trigger deploy
  --ci-timeout <seconds>   Max time to wait for CI (default: 600)
  --deploy-timeout <secs>  Max time to wait for deploy (default: 600)
  -h, --help               Show this help message
USAGE
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sha)          SHA="$2";            shift 2 ;;
        --version)      VERSION="$2";        shift 2 ;;
        --component)    COMPONENT="$2";      shift 2 ;;
        --dry-run)      DRY_RUN=true;        shift   ;;
        --skip-ci)      SKIP_CI=true;        shift   ;;
        --skip-deploy)  SKIP_DEPLOY=true;    shift   ;;
        --ci-timeout)   CI_TIMEOUT="$2";     shift 2 ;;
        --deploy-timeout) DEPLOY_TIMEOUT="$2"; shift 2 ;;
        -h|--help)      usage ;;
        *)              err "Unknown option: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------

[[ -n "$VERSION" ]]   || err "Missing required --version <x.y.z>"
[[ -n "$COMPONENT" ]] || err "Missing required --component <a2a-gateway|a2a-website|all>"

# Validate version format
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    err "Invalid version format: '$VERSION'. Expected x.y.z (e.g. 1.2.3)"
fi

# Validate component
case "$COMPONENT" in
    a2a-gateway|a2a-website|all) ;;
    *) err "Invalid component: '$COMPONENT'. Must be: a2a-gateway, a2a-website, or all" ;;
esac

# Default SHA to HEAD
if [[ -z "$SHA" ]]; then
    SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
    info "No --sha specified, using HEAD: ${SHA:0:8}"
fi

# Validate SHA exists
if ! git -C "$REPO_ROOT" cat-file -e "$SHA" 2>/dev/null; then
    err "Git commit not found: $SHA"
fi

# Resolve to full SHA
SHA=$(git -C "$REPO_ROOT" rev-parse "$SHA")

# Check gh CLI (only needed when not dry-run)
if [[ "$DRY_RUN" == false ]] && ! command -v gh &>/dev/null; then
    err "gh CLI not found. Install: https://cli.github.com"
fi

# Check for clean working tree
if ! git -C "$REPO_ROOT" diff --quiet 2>/dev/null || \
   ! git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null; then
    err "Working tree has uncommitted changes. Commit or stash before releasing."
fi

# Check tag doesn't already exist
if git -C "$REPO_ROOT" tag -l "v${VERSION}" | grep -q "v${VERSION}"; then
    err "Tag v${VERSION} already exists. Choose a different version."
fi

RELEASE_BRANCH="release/${VERSION}"

# Check branch doesn't already exist
if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/${RELEASE_BRANCH}" 2>/dev/null; then
    err "Branch '${RELEASE_BRANCH}' already exists locally."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Release Plan"
info "Version:   ${VERSION}"
info "SHA:       ${SHA:0:8} ($(git -C "$REPO_ROOT" log --oneline -1 "$SHA"))"
info "Branch:    ${RELEASE_BRANCH}"
info "Component: ${COMPONENT}"
info "Dry run:   ${DRY_RUN}"
echo ""

if [[ "$DRY_RUN" == false ]]; then
    read -rp "Proceed with release? [y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        info "Release cancelled."
        exit 0
    fi
fi

# ---------------------------------------------------------------------------
# Step 1: Create release branch
# ---------------------------------------------------------------------------

header "Step 1: Create release branch"

cd "$REPO_ROOT"
git checkout -b "$RELEASE_BRANCH" "$SHA"
log "Created branch '${RELEASE_BRANCH}' at ${SHA:0:8}"

# ---------------------------------------------------------------------------
# Step 2: Bump version numbers
# ---------------------------------------------------------------------------

header "Step 2: Bump versions to ${VERSION}"

# Bump DEBIAN/control files
bump_deb_version() {
    local control_file="$1"
    if [[ -f "$control_file" ]]; then
        sed -i "s/^Version:.*/Version: ${VERSION}/" "$control_file"
        log "Bumped $(basename "$(dirname "$(dirname "$control_file")")")/DEBIAN/control → ${VERSION}"
    fi
}

# Always bump all package versions for consistency
for pkg_dir in "$REPO_ROOT"/package/*/DEBIAN/control; do
    bump_deb_version "$pkg_dir"
done

# Bump pyproject.toml (root)
if [[ -f "$REPO_ROOT/pyproject.toml" ]]; then
    sed -i "s/^version = \".*\"/version = \"${VERSION}\"/" "$REPO_ROOT/pyproject.toml"
    log "Bumped pyproject.toml → ${VERSION}"
fi

# Bump sdk/pyproject.toml
if [[ -f "$REPO_ROOT/sdk/pyproject.toml" ]]; then
    sed -i "s/^version = \".*\"/version = \"${VERSION}\"/" "$REPO_ROOT/sdk/pyproject.toml"
    log "Bumped sdk/pyproject.toml → ${VERSION}"
fi

# Bump gateway version (used by /v1/health endpoint)
VERSION_PY="$REPO_ROOT/gateway/src/_version.py"
if [[ -f "$VERSION_PY" ]]; then
    sed -i "s/^__version__ = \".*\"/__version__ = \"${VERSION}\"/" "$VERSION_PY"
    log "Bumped gateway/_version.py → ${VERSION}"
fi

# ---------------------------------------------------------------------------
# Step 3: Generate release notes and changelog
# ---------------------------------------------------------------------------

header "Step 3: Generate release notes"

# Find the previous tag for generating notes
PREV_TAG=$(git tag --sort=-v:refname | head -1 || echo "")

if [[ -n "$PREV_TAG" ]]; then
    info "Previous tag: ${PREV_TAG}"
    RANGE="${PREV_TAG}..${SHA}"
else
    info "No previous tags — using full history"
    RANGE="$SHA"
fi

# Generate release notes
RELEASE_NOTES_FILE="$REPO_ROOT/.release-notes-${VERSION}.md"

{
    echo "# Release v${VERSION}"
    echo ""
    echo "**Date:** $(date -u +%Y-%m-%d)"
    echo "**Commit:** ${SHA:0:8}"
    if [[ -n "$PREV_TAG" ]]; then
        echo "**Previous:** ${PREV_TAG}"
    fi
    echo ""
    echo "## Changes"
    echo ""

    # Group commits by type
    declare -A sections=(
        ["feat"]="### Features"
        ["fix"]="### Bug Fixes"
        ["refactor"]="### Refactoring"
        ["docs"]="### Documentation"
        ["infra"]="### Infrastructure"
        ["test"]="### Tests"
        ["chore"]="### Chores"
    )

    for prefix in feat fix refactor docs infra test chore; do
        commits=$(git log --oneline "$RANGE" --grep="^${prefix}" 2>/dev/null || true)
        if [[ -n "$commits" ]]; then
            echo "${sections[$prefix]}"
            echo ""
            while IFS= read -r line; do
                sha_short="${line%% *}"
                msg="${line#* }"
                echo "- ${msg} (\`${sha_short}\`)"
            done <<< "$commits"
            echo ""
        fi
    done

    # Catch any commits not matching a prefix
    other_commits=$(git log --oneline "$RANGE" \
        --invert-grep \
        --grep="^feat" --grep="^fix" --grep="^refactor" \
        --grep="^docs" --grep="^infra" --grep="^test" --grep="^chore" \
        2>/dev/null || true)
    if [[ -n "$other_commits" ]]; then
        echo "### Other"
        echo ""
        while IFS= read -r line; do
            sha_short="${line%% *}"
            msg="${line#* }"
            echo "- ${msg} (\`${sha_short}\`)"
        done <<< "$other_commits"
        echo ""
    fi

    echo "## Components"
    echo ""
    echo "| Package | Version |"
    echo "|---------|---------|"
    for pkg_dir in "$REPO_ROOT"/package/*/DEBIAN/control; do
        pkg_name=$(grep '^Package:' "$pkg_dir" | awk '{print $2}')
        pkg_ver=$(grep '^Version:' "$pkg_dir" | awk '{print $2}')
        echo "| ${pkg_name} | ${pkg_ver} |"
    done
    echo ""
} > "$RELEASE_NOTES_FILE"

log "Release notes written to $(basename "$RELEASE_NOTES_FILE")"

# ---------------------------------------------------------------------------
# Step 4: Update CHANGELOG.md
# ---------------------------------------------------------------------------

header "Step 4: Update CHANGELOG"

CHANGELOG="$REPO_ROOT/CHANGELOG.md"

# Prepare the new entry
NEW_ENTRY=$(cat "$RELEASE_NOTES_FILE")

if [[ -f "$CHANGELOG" ]]; then
    # Insert new entry after the title line
    {
        head -1 "$CHANGELOG"
        echo ""
        echo "$NEW_ENTRY"
        echo "---"
        echo ""
        tail -n +2 "$CHANGELOG"
    } > "${CHANGELOG}.tmp"
    mv "${CHANGELOG}.tmp" "$CHANGELOG"
    log "Prepended v${VERSION} entry to CHANGELOG.md"
else
    {
        echo "# Changelog"
        echo ""
        echo "$NEW_ENTRY"
    } > "$CHANGELOG"
    log "Created CHANGELOG.md with v${VERSION} entry"
fi

# Clean up temp file
rm -f "$RELEASE_NOTES_FILE"

# ---------------------------------------------------------------------------
# Step 5: Commit release changes
# ---------------------------------------------------------------------------

header "Step 5: Commit release"

# Stage only release-related files (not untracked files)
git -C "$REPO_ROOT" add \
    package/*/DEBIAN/control \
    CHANGELOG.md
[[ -f "$REPO_ROOT/pyproject.toml" ]] && git -C "$REPO_ROOT" add pyproject.toml || true
[[ -f "$REPO_ROOT/sdk/pyproject.toml" ]] && git -C "$REPO_ROOT" add sdk/pyproject.toml || true
[[ -f "$REPO_ROOT/gateway/src/_version.py" ]] && git -C "$REPO_ROOT" add gateway/src/_version.py || true

git -C "$REPO_ROOT" commit -m "$(cat <<EOF
release: v${VERSION}

Bump all package versions to ${VERSION}.
Update CHANGELOG.md with release notes.

Component: ${COMPONENT}
SHA: ${SHA:0:8}
EOF
)"

RELEASE_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)
log "Release commit: ${RELEASE_SHA:0:8}"

# ---------------------------------------------------------------------------
# Step 6: Push release branch
# ---------------------------------------------------------------------------

if [[ "$DRY_RUN" == true ]]; then
    header "Dry Run Complete"
    info "Release branch '${RELEASE_BRANCH}' created locally."
    info "Version bumped to ${VERSION}. CHANGELOG.md updated."
    info "To push manually:  git push -u origin ${RELEASE_BRANCH}"
    info "To clean up:       git checkout main && git branch -D ${RELEASE_BRANCH}"
    exit 0
fi

header "Step 6: Push release branch"

git -C "$REPO_ROOT" push -u origin "$RELEASE_BRANCH"
log "Pushed '${RELEASE_BRANCH}' to origin"

# ---------------------------------------------------------------------------
# Step 7: Wait for CI to pass
# ---------------------------------------------------------------------------

if [[ "$SKIP_CI" == false ]]; then
    header "Step 7: Wait for CI"

    info "Waiting for CI checks on ${RELEASE_BRANCH}..."

    elapsed=0
    ci_passed=false

    # Give GitHub a moment to register the push
    sleep 5

    # Find the workflow run triggered by our push
    RUN_ID=""
    for attempt in $(seq 1 10); do
        RUN_ID=$(gh run list \
            --branch "$RELEASE_BRANCH" \
            --limit 1 \
            --json databaseId \
            --jq '.[0].databaseId' 2>/dev/null || echo "")
        if [[ -n "$RUN_ID" && "$RUN_ID" != "null" ]]; then
            break
        fi
        sleep 3
    done

    if [[ -z "$RUN_ID" || "$RUN_ID" == "null" ]]; then
        err "Could not find CI run for ${RELEASE_BRANCH}. Check: gh run list --branch ${RELEASE_BRANCH}"
    fi

    info "CI run ID: ${RUN_ID}"

    while (( elapsed < CI_TIMEOUT )); do
        run_result=$(gh run view "$RUN_ID" --json status,conclusion \
            --jq '.status + ":" + (.conclusion // "")' 2>/dev/null || echo "unknown:")

        run_status="${run_result%%:*}"
        run_conclusion="${run_result##*:}"

        if [[ "$run_status" == "completed" ]]; then
            if [[ "$run_conclusion" == "success" ]]; then
                ci_passed=true
            else
                err "CI failed (conclusion: ${run_conclusion}) on ${RELEASE_BRANCH}. Check: gh run view ${RUN_ID}"
            fi
            break
        fi

        info "CI status: ${run_status} (${elapsed}s / ${CI_TIMEOUT}s)"
        sleep "$POLL_INTERVAL"
        elapsed=$((elapsed + POLL_INTERVAL))
    done

    if [[ "$ci_passed" == true ]]; then
        log "CI passed on ${RELEASE_BRANCH}"
    else
        err "CI timed out after ${CI_TIMEOUT}s. Check: gh run list --branch ${RELEASE_BRANCH}"
    fi
else
    warn "Skipping CI wait (--skip-ci)"
fi

# ---------------------------------------------------------------------------
# Step 8: Trigger production deployment
# ---------------------------------------------------------------------------

if [[ "$SKIP_DEPLOY" == true ]]; then
    header "Deploy Skipped"
    info "Release branch pushed and CI passed."
    info "To deploy manually:"
    info "  gh workflow run 'Deploy Production' --ref ${RELEASE_BRANCH} -f confirm=deploy -f component=${COMPONENT}"
    exit 0
fi

header "Step 8: Deploy to production"

info "Triggering production deployment for component=${COMPONENT}..."

gh workflow run "Deploy Production" \
    --ref "$RELEASE_BRANCH" \
    -f confirm=deploy \
    -f component="$COMPONENT"

log "Deploy workflow triggered"

# ---------------------------------------------------------------------------
# Step 9: Wait for deployment
# ---------------------------------------------------------------------------

header "Step 9: Wait for deployment"

# Give GitHub a moment to create the workflow run
sleep 10

# Find the run ID for our deploy workflow
RUN_ID=""
for attempt in $(seq 1 10); do
    RUN_ID=$(gh run list \
        --workflow "Deploy Production" \
        --branch "$RELEASE_BRANCH" \
        --limit 1 \
        --json databaseId \
        --jq '.[0].databaseId' 2>/dev/null || echo "")

    if [[ -n "$RUN_ID" ]]; then
        break
    fi
    info "Waiting for deploy run to appear (attempt ${attempt})..."
    sleep 5
done

if [[ -z "$RUN_ID" ]]; then
    err "Could not find deploy workflow run. Check: gh run list --workflow 'Deploy Production'"
fi

info "Deploy run ID: ${RUN_ID}"
info "Monitor: gh run watch ${RUN_ID}"

elapsed=0
deploy_passed=false

while (( elapsed < DEPLOY_TIMEOUT )); do
    run_status=$(gh run view "$RUN_ID" --json status,conclusion \
        --jq '.status + ":" + (.conclusion // "")' 2>/dev/null || echo "unknown:")

    status="${run_status%%:*}"
    conclusion="${run_status##*:}"

    if [[ "$status" == "completed" ]]; then
        if [[ "$conclusion" == "success" ]]; then
            deploy_passed=true
        fi
        break
    fi

    info "Deploy status: ${status} (${elapsed}s / ${DEPLOY_TIMEOUT}s)"
    sleep "$POLL_INTERVAL"
    elapsed=$((elapsed + POLL_INTERVAL))
done

if [[ "$deploy_passed" == true ]]; then
    log "Deployment successful!"
else
    deploy_url=$(gh run view "$RUN_ID" --json url --jq '.url' 2>/dev/null || echo "")
    err "Deployment failed or timed out. Check: ${deploy_url:-gh run view ${RUN_ID}}"
fi

# ---------------------------------------------------------------------------
# Step 10: Tag release
# ---------------------------------------------------------------------------

header "Step 10: Tag release"

git -C "$REPO_ROOT" tag -a "v${VERSION}" -m "Release v${VERSION}" "$RELEASE_SHA"
git -C "$REPO_ROOT" push origin "v${VERSION}"
log "Created and pushed tag v${VERSION}"

# ---------------------------------------------------------------------------
# Step 11: Update main with release
# ---------------------------------------------------------------------------

header "Step 11: Update main branch"

git -C "$REPO_ROOT" checkout main
git -C "$REPO_ROOT" pull origin main
git -C "$REPO_ROOT" merge --no-ff "$RELEASE_BRANCH" -m "$(cat <<EOF
Merge release v${VERSION} into main

Release branch: ${RELEASE_BRANCH}
Component: ${COMPONENT}
EOF
)"
git -C "$REPO_ROOT" push origin main
log "Merged ${RELEASE_BRANCH} into main"

# Clean up release branch
git -C "$REPO_ROOT" branch -d "$RELEASE_BRANCH"
git -C "$REPO_ROOT" push origin --delete "$RELEASE_BRANCH"
log "Deleted release branch ${RELEASE_BRANCH}"

# ---------------------------------------------------------------------------
# Step 12: Summary
# ---------------------------------------------------------------------------

header "Release v${VERSION} Complete"
echo ""
log "Version:    v${VERSION}"
log "Branch:     main (merged from ${RELEASE_BRANCH})"
log "Commit:     ${RELEASE_SHA:0:8}"
log "Component:  ${COMPONENT}"
log "Tag:        v${VERSION}"
log "Deploy run: gh run view ${RUN_ID}"
echo ""
info "Next steps:"
info "  - Verify production: curl -sf https://api.greenhelix.net/v1/health"
echo ""
