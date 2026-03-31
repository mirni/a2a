#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Universal packaging driver
#
# Builds Debian packages from the package/ symlink tree and/or a Python wheel
# for the SDK.
#
# Usage:
#   ./scripts/create_package.sh a2a-gateway       # one deb
#   ./scripts/create_package.sh a2a-gateway-test   # test deb
#   ./scripts/create_package.sh a2a-website        # website deb
#   ./scripts/create_package.sh a2a-sdk            # python wheel
#   ./scripts/create_package.sh ALL                # all packages
#
# Output:
#   All artifacts written to dist/
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
PACKAGE_DIR="$REPO_ROOT/package"

# All deb packages available
DEB_PACKAGES=(a2a-gateway a2a-gateway-test a2a-website)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo -e "\033[0;32m[+]\033[0m $*"; }
warn() { echo -e "\033[1;33m[!]\033[0m $*"; }
err()  { echo -e "\033[0;31m[x]\033[0m $*" >&2; exit 1; }

usage() {
    echo "Usage: $0 <package-name|ALL>"
    echo ""
    echo "Packages:"
    echo "  a2a-gateway       Production gateway deb"
    echo "  a2a-gateway-test  Staging/test gateway deb"
    echo "  a2a-website       Static website deb"
    echo "  a2a-sdk           Python SDK wheel"
    echo "  ALL               Build all packages"
    exit 1
}

# ---------------------------------------------------------------------------
# Strip build artifacts from a staging directory
# ---------------------------------------------------------------------------

strip_artifacts() {
    local dir="$1"

    find "$dir" -type d -name '.git' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name 'node_modules' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name '.ruff_cache' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -type d -name '.mypy_cache' -exec rm -rf {} + 2>/dev/null || true
    find "$dir" -name '*.pyc' -delete 2>/dev/null || true
    find "$dir" -name '.env' -delete 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Build a single deb package
# ---------------------------------------------------------------------------

build_deb() {
    local pkg_name="$1"
    local pkg_src="$PACKAGE_DIR/$pkg_name"

    if [[ ! -d "$pkg_src" ]]; then
        err "Package directory not found: $pkg_src"
    fi

    if [[ ! -f "$pkg_src/DEBIAN/control" ]]; then
        err "Missing DEBIAN/control in $pkg_src"
    fi

    # Read version from control file
    local version
    version=$(grep '^Version:' "$pkg_src/DEBIAN/control" | awk '{print $2}')
    local deb_name="${pkg_name}_${version}_all"

    log "Building ${deb_name}.deb..."

    # Create temporary staging directory
    local staging
    staging=$(mktemp -d)
    trap "rm -rf '$staging'" RETURN

    local dest="$staging/$pkg_name"
    mkdir -p "$dest"

    # Copy DEBIAN metadata (always regular files)
    cp -r "$pkg_src/DEBIAN" "$dest/DEBIAN"

    # Copy opt/ with symlink dereferencing — resolves repo content symlinks
    if [[ -d "$pkg_src/opt" ]]; then
        cp -rL "$pkg_src/opt" "$dest/opt"
    fi

    # Copy etc/ (systemd units, nginx configs) — regular files
    if [[ -d "$pkg_src/etc" ]]; then
        cp -r "$pkg_src/etc" "$dest/etc"
    fi

    # Copy usr/ preserving symlinks — these are install-time symlinks
    # (e.g., /usr/local/bin/deploy_a2a.sh → /opt/a2a/scripts/deploy_a2a.sh)
    # that should remain as symlinks in the deb
    if [[ -d "$pkg_src/usr" ]]; then
        cp -r "$pkg_src/usr" "$dest/usr"
    fi

    # Ensure DEBIAN scripts are executable
    chmod 755 "$dest/DEBIAN/postinst" 2>/dev/null || true
    chmod 755 "$dest/DEBIAN/prerm" 2>/dev/null || true

    # Strip build artifacts from the staged content (skip DEBIAN dir)
    if [[ -d "$dest/opt" ]]; then
        strip_artifacts "$dest/opt"
    fi

    # Make all .sh scripts executable in the package (only real files)
    find "$dest/opt" -name '*.sh' -type f -exec chmod 755 {} + 2>/dev/null || true
    find "$dest/opt" -name '*.bash' -type f -exec chmod 644 {} + 2>/dev/null || true

    # Build the deb
    dpkg-deb --root-owner-group --build "$dest" "$DIST_DIR/${deb_name}.deb"

    log "Built: $DIST_DIR/${deb_name}.deb ($(du -h "$DIST_DIR/${deb_name}.deb" | cut -f1))"

    # Reset trap (staging cleaned up by RETURN trap)
    trap - RETURN
    rm -rf "$staging"
}

# ---------------------------------------------------------------------------
# Build SDK wheel
# ---------------------------------------------------------------------------

build_sdk() {
    log "Building a2a-sdk wheel..."

    if [[ ! -d "$REPO_ROOT/sdk" ]]; then
        err "sdk/ directory not found"
    fi

    pip wheel --no-deps --wheel-dir "$DIST_DIR" "$REPO_ROOT/sdk/" 2>&1 | tail -1
    log "SDK wheel built in $DIST_DIR/"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

[[ $# -ge 1 ]] || usage

TARGET="$1"

mkdir -p "$DIST_DIR"

case "$TARGET" in
    ALL)
        for pkg in "${DEB_PACKAGES[@]}"; do
            build_deb "$pkg"
        done
        build_sdk
        log "All packages built in $DIST_DIR/"
        ls -lh "$DIST_DIR/"
        ;;
    a2a-sdk)
        build_sdk
        ;;
    a2a-gateway|a2a-gateway-test|a2a-website)
        build_deb "$TARGET"
        ;;
    *)
        err "Unknown package: $TARGET"
        ;;
esac
