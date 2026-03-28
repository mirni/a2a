#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Build and verify Docker image
#
# Usage:
#   scripts/ci/docker_build_verify.sh [image-tag]
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE_TAG="${1:-a2a-gateway:ci}"
CONTAINER_NAME="a2a-ci-$$"

cleanup() {
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
}
trap cleanup EXIT

docker build -t "$IMAGE_TAG" "$REPO_ROOT"

docker run -d --name "$CONTAINER_NAME" -p 8000:8000 "$IMAGE_TAG"
sleep 5

if ! curl -sf http://localhost:8000/v1/health > /dev/null 2>&1; then
    echo "Health check failed — container logs:" >&2
    docker logs "$CONTAINER_NAME" >&2
    exit 1
fi

echo "Container verified successfully"
