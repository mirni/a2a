#!/usr/bin/env bash
# =============================================================================
# Build a2a-server Debian package
#
# Usage:
#   cd /workdir && bash packaging/build-deb.sh
#
# Output:
#   a2a-server_0.1.0_all.deb in current directory
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_NAME="a2a-server"
PKG_VERSION="0.1.0"
DEB_NAME="${PKG_NAME}_${PKG_VERSION}_all"

echo "[+] Building ${DEB_NAME}.deb..."

# ---------------------------------------------------------------------------
# Create staging directory
# ---------------------------------------------------------------------------

STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "$STAGING/DEBIAN"
mkdir -p "$STAGING/opt/a2a"
mkdir -p "$STAGING/usr/local/bin"

# ---------------------------------------------------------------------------
# DEBIAN metadata
# ---------------------------------------------------------------------------

cp "$REPO_ROOT/packaging/control"  "$STAGING/DEBIAN/control"
cp "$REPO_ROOT/packaging/postinst" "$STAGING/DEBIAN/postinst"
cp "$REPO_ROOT/packaging/prerm"    "$STAGING/DEBIAN/prerm"
chmod 755 "$STAGING/DEBIAN/postinst"
chmod 755 "$STAGING/DEBIAN/prerm"

# ---------------------------------------------------------------------------
# Application code → /opt/a2a/
# ---------------------------------------------------------------------------

# Core application directories
for dir in gateway products sdk server website; do
    if [[ -d "$REPO_ROOT/$dir" ]]; then
        cp -r "$REPO_ROOT/$dir" "$STAGING/opt/a2a/$dir"
    fi
done

# Copy SDK TypeScript if present
if [[ -d "$REPO_ROOT/sdk-ts" ]]; then
    cp -r "$REPO_ROOT/sdk-ts" "$STAGING/opt/a2a/sdk-ts"
fi

# Copy root-level Python/config files needed by the app
for f in pyproject.toml setup.py setup.cfg; do
    if [[ -f "$REPO_ROOT/$f" ]]; then
        cp "$REPO_ROOT/$f" "$STAGING/opt/a2a/$f"
    fi
done

# ---------------------------------------------------------------------------
# Deployment scripts → /usr/local/bin/ AND /opt/a2a/scripts/
# ---------------------------------------------------------------------------

# Copy scripts dir to /opt/a2a/scripts/ (so relative sourcing works)
cp -r "$REPO_ROOT/scripts" "$STAGING/opt/a2a/scripts"

# Symlink each script to /usr/local/bin/ for PATH access
for script in common.bash create_user.sh deploy_a2a.sh deploy_a2a-gateway.sh deploy_website.sh; do
    if [[ -f "$REPO_ROOT/scripts/$script" ]]; then
        ln -sf "/opt/a2a/scripts/$script" "$STAGING/usr/local/bin/$script"
    fi
done

# Make all .sh scripts executable
find "$STAGING/opt/a2a/scripts" -name '*.sh' -exec chmod 755 {} +
find "$STAGING/opt/a2a/scripts" -name '*.bash' -exec chmod 644 {} +

# ---------------------------------------------------------------------------
# Clean up unwanted files from package
# ---------------------------------------------------------------------------

# Remove .git directories, __pycache__, .pyc files, test data
find "$STAGING/opt/a2a" -type d -name '.git' -exec rm -rf {} + 2>/dev/null || true
find "$STAGING/opt/a2a" -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
find "$STAGING/opt/a2a" -type d -name 'node_modules' -exec rm -rf {} + 2>/dev/null || true
find "$STAGING/opt/a2a" -name '*.pyc' -delete 2>/dev/null || true
find "$STAGING/opt/a2a" -name '.env' -delete 2>/dev/null || true
find "$STAGING/opt/a2a" -type d -name '.pytest_cache' -exec rm -rf {} + 2>/dev/null || true
find "$STAGING/opt/a2a" -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true

# ---------------------------------------------------------------------------
# Build the .deb
# ---------------------------------------------------------------------------

dpkg-deb --root-owner-group --build "$STAGING" "${DEB_NAME}.deb"

echo "[+] Built: $(pwd)/${DEB_NAME}.deb"
echo "[+] Size: $(du -h "${DEB_NAME}.deb" | cut -f1)"
echo ""
echo "Install with:"
echo "  sudo dpkg -i ${DEB_NAME}.deb"
echo "  sudo apt-get install -f  # resolve dependencies"
