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
#   # Re-run publishing for an existing release (publish-only mode)
#   ./scripts/release.sh --version 1.0.7 --component all --skip-ci --skip-deploy --publish-pypi
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
# Bootstrap: load .env and activate Python venv
# ---------------------------------------------------------------------------

# Source .env for deployment tokens (PYPI, NPM, DOCKER, GITHUB, etc.)
if [[ -f "$REPO_ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/.env"
    set +a
fi

# Ensure a working Python venv exists and activate it
VENV_DIR="$REPO_ROOT/.venv"
if [[ ! -x "$VENV_DIR/bin/python3" ]] || ! "$VENV_DIR/bin/python3" --version &>/dev/null; then
    echo "[i] Creating Python venv at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip 2>/dev/null
    if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
        "$VENV_DIR/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt" 2>/dev/null
    fi
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

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
PUBLISH=false
PUBLISH_PYPI=false
PUBLISH_NPM=false
PUBLISH_DOCKER=false

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
  --publish                (deprecated — Docker Hub publish now runs in
                            .github/workflows/publish.yml on tag push; pass
                            --publish-docker for an emergency local override)
  --publish-pypi           (deprecated — now via GitHub Actions on tag push)
  --publish-npm            (deprecated — now via GitHub Actions on tag push)
  --publish-docker         Emergency local override: build and push the
                            Docker image from this machine instead of CI.
                            Useful if CI is down or the Dockerfile changed
                            in a way that breaks the CI runner. Normal
                            releases should rely on publish.yml's
                            publish-docker job instead.
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
        --publish)      PUBLISH=true;        shift   ;;
        --publish-pypi) PUBLISH_PYPI=true;   shift   ;;
        --publish-npm)  PUBLISH_NPM=true;    shift   ;;
        --publish-docker) PUBLISH_DOCKER=true; shift  ;;
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

# Deprecate --publish-pypi and --publish-npm (now handled by .github/workflows/publish.yml on tag push)
if [[ "$PUBLISH_PYPI" == true ]]; then
    warn "--publish-pypi is deprecated: PyPI publishing is now triggered automatically via GitHub Actions when the version tag is pushed."
    PUBLISH_PYPI=false
fi
if [[ "$PUBLISH_NPM" == true ]]; then
    warn "--publish-npm is deprecated: npm publishing is now triggered automatically via GitHub Actions when the version tag is pushed."
    PUBLISH_NPM=false
fi

# Resolve --publish umbrella flag. Historically this enabled the local
# Docker push because CI could not reach Docker Hub. Starting with
# v1.2.6 the ``publish-docker`` job in publish.yml does this on every
# tag push, so ``--publish`` on its own is a no-op. ``--publish-docker``
# is preserved as an explicit emergency override for the rare case
# where CI is down and a hot-fix image must ship from a laptop.
if [[ "$PUBLISH" == true ]]; then
    warn "--publish is a no-op now (publish.yml ships the Docker image in CI)."
    warn "Use --publish-docker explicitly if you really want a local push."
fi
WANT_PUBLISH=$([[ "$PUBLISH_DOCKER" == true ]] && echo true || echo false)

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

# ---------------------------------------------------------------------------
# Detect publish-only mode: re-running publish for an existing release
# ---------------------------------------------------------------------------
PUBLISH_ONLY=false
if [[ "$WANT_PUBLISH" == true && "$SKIP_CI" == true && "$SKIP_DEPLOY" == true ]]; then
    if git -C "$REPO_ROOT" tag -l "v${VERSION}" | grep -q "v${VERSION}"; then
        PUBLISH_ONLY=true
        info "Tag v${VERSION} exists — publish-only mode (skipping steps 1–11)"
    fi
fi

RELEASE_BRANCH="release/${VERSION}"

if [[ "$PUBLISH_ONLY" == false ]]; then
    # Check for clean working tree
    if ! git -C "$REPO_ROOT" diff --quiet 2>/dev/null || \
       ! git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null; then
        err "Working tree has uncommitted changes. Commit or stash before releasing."
    fi

    # Check tag doesn't already exist
    if git -C "$REPO_ROOT" tag -l "v${VERSION}" | grep -q "v${VERSION}"; then
        err "Tag v${VERSION} already exists. Choose a different version."
    fi

    # Check branch doesn't already exist
    if git -C "$REPO_ROOT" show-ref --verify --quiet "refs/heads/${RELEASE_BRANCH}" 2>/dev/null; then
        err "Branch '${RELEASE_BRANCH}' already exists locally."
    fi
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

header "Release Plan"
info "Version:   ${VERSION}"
info "SHA:       ${SHA:0:8} ($(git -C "$REPO_ROOT" log --oneline -1 "$SHA"))"
if [[ "$PUBLISH_ONLY" == true ]]; then
    info "Mode:      publish-only (re-run)"
else
    info "Branch:    ${RELEASE_BRANCH}"
fi
info "Component: ${COMPONENT}"
info "Dry run:   ${DRY_RUN}"
echo ""

if [[ "$DRY_RUN" == false && "$PUBLISH_ONLY" == false ]]; then
    read -rp "Proceed with release? [y/N] " confirm
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        info "Release cancelled."
        exit 0
    fi
fi

# Skip steps 1–11 in publish-only mode
if [[ "$PUBLISH_ONLY" == false ]]; then

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

# Bump sdk-ts/package.json (TypeScript SDK)
if [[ -f "$REPO_ROOT/sdk-ts/package.json" ]]; then
    (cd "$REPO_ROOT/sdk-ts" && npm version "$VERSION" --no-git-tag-version --allow-same-version 2>/dev/null)
    log "Bumped sdk-ts/package.json → ${VERSION}"
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
[[ -f "$REPO_ROOT/sdk-ts/package.json" ]] && git -C "$REPO_ROOT" add sdk-ts/package.json sdk-ts/package-lock.json || true

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

    # Find the Release workflow run triggered by our push
    RUN_ID=""
    for attempt in $(seq 1 10); do
        RUN_ID=$(gh run list \
            --workflow "Release" \
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
        err "Could not find Release workflow run for ${RELEASE_BRANCH}. Check: gh run list --workflow Release --branch ${RELEASE_BRANCH}"
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
    if [[ "$WANT_PUBLISH" == false ]]; then
        exit 0
    fi
else

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
info "Tag v${VERSION} pushed — PyPI + npm publish triggered via GitHub Actions"
info "Monitor: gh run list --workflow Publish --limit 1"

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

fi  # end of SKIP_DEPLOY else block (steps 8–11)

fi  # end of PUBLISH_ONLY == false guard (steps 1–11)

# ---------------------------------------------------------------------------
# Step 12: Publish packages (optional)
# ---------------------------------------------------------------------------

if [[ "$PUBLISH_DOCKER" == true ]]; then
    header "Step 12: Publish Docker image"
fi

# NOTE: PyPI and npm publishing is now handled by .github/workflows/publish.yml
# triggered automatically by the version tag push in step 10.

# Pre-flight checks for publish targets
if [[ "$PUBLISH_DOCKER" == true ]] && ! command -v docker &>/dev/null; then
    warn "docker not found — skipping Docker publish"
    PUBLISH_DOCKER=false
fi

# Track publish failures
PUBLISH_FAILURES=0

# --- Docker ---
if [[ "$PUBLISH_DOCKER" == true ]]; then
    info "Publishing Docker image to Docker Hub..."
    if [[ -z "${DOCKER_DEPLOYMENT_TOKEN:-}" ]]; then
        warn "DOCKER_DEPLOYMENT_TOKEN not set — skipping Docker publish"
    elif (
        DOCKER_IMAGE="greenhelix/a2a-gateway"
        echo "$DOCKER_DEPLOYMENT_TOKEN" | docker login --username greenhelix --password-stdin
        docker build -t "${DOCKER_IMAGE}:${VERSION}" -t "${DOCKER_IMAGE}:latest" "$REPO_ROOT"
        docker push "${DOCKER_IMAGE}:${VERSION}"
        docker push "${DOCKER_IMAGE}:latest"
        docker logout
    ); then
        log "Published greenhelix/a2a-gateway:${VERSION} to Docker Hub"
    else
        warn "Docker publish failed (exit $?) — continuing"
        PUBLISH_FAILURES=$((PUBLISH_FAILURES + 1))
    fi
fi

if (( PUBLISH_FAILURES > 0 )); then
    warn "${PUBLISH_FAILURES} publish target(s) failed — check output above"
fi

# ---------------------------------------------------------------------------
# Step 13: Post-publish smoke tests (Docker only; PyPI/npm verified by publish.yml)
# ---------------------------------------------------------------------------

VERIFY_FAILURES=0

if [[ "$PUBLISH_DOCKER" == true ]]; then
    header "Step 13: Post-publish verification (Docker)"
    info "Waiting 30s for Docker Hub to propagate..."
    sleep 30
fi

# --- Verify Docker ---
if [[ "$PUBLISH_DOCKER" == true ]] && command -v docker &>/dev/null; then
    info "Verifying greenhelix/a2a-gateway:${VERSION} on Docker Hub..."
    if docker pull "greenhelix/a2a-gateway:${VERSION}" >/dev/null 2>&1 && \
       docker run --rm "greenhelix/a2a-gateway:${VERSION}" \
           python -c "from gateway.src._version import __version__; assert __version__ == '${VERSION}'; print('version OK')" 2>/dev/null; then
        log "Docker: greenhelix/a2a-gateway:${VERSION} pulls and runs OK"
    else
        warn "Docker: greenhelix/a2a-gateway:${VERSION} verification FAILED"
        VERIFY_FAILURES=$((VERIFY_FAILURES + 1))
    fi
fi

if (( VERIFY_FAILURES > 0 )); then
    warn "${VERIFY_FAILURES} post-publish verification(s) failed — packages may be broken!"
fi

# ---------------------------------------------------------------------------
# Step 14: Summary
# ---------------------------------------------------------------------------

if [[ "$PUBLISH_ONLY" == true ]]; then
    header "Publish v${VERSION} Complete"
else
    header "Release v${VERSION} Complete"
fi
echo ""
log "Version:    v${VERSION}"
if [[ "$PUBLISH_ONLY" == false ]]; then
    log "Branch:     main (merged from ${RELEASE_BRANCH})"
    log "Commit:     ${RELEASE_SHA:0:8}"
    log "Tag:        v${VERSION}"
    [[ -n "${RUN_ID:-}" ]] && log "Deploy run: gh run view ${RUN_ID}"
fi
log "Component:  ${COMPONENT}"
if [[ "$WANT_PUBLISH" == true ]]; then
    [[ "$PUBLISH_DOCKER" == true ]] && log "Published:  docker"
fi
log "SDK publish: PyPI + npm triggered via GitHub Actions (publish.yml)"
log "Monitor:     gh run list --workflow Publish --limit 1"
if (( ${PUBLISH_FAILURES:-0} > 0 )); then
    warn "Some publish targets failed — re-run with --skip-ci --skip-deploy --publish-docker"
fi
if (( ${VERIFY_FAILURES:-0} > 0 )); then
    warn "Some post-publish verifications failed — check packages manually!"
fi
echo ""
info "Next steps:"
info "  - Verify production: curl -sf https://api.greenhelix.net/v1/health"
info "  - Verify SDK publish: gh run list --workflow Publish --limit 1"
echo ""
