#!/usr/bin/env bash
# =============================================================================
# Generate an Ed25519 signing key + DNS TXT record for mcp-publisher DNS auth.
#
# Usage:
#   scripts/mcp_registry/generate_dns_key.sh [domain]
#
# Default domain: greenhelix.net
#
# This script produces:
#   1. key.pem               — private key (DO NOT COMMIT, add to .gitignore)
#   2. A printed TXT record  — add to the domain's DNS provider
#   3. A printed private key — store in GitHub secret MCP_REGISTRY_PRIVATE_KEY
#
# The private key format is the raw hex string expected by
# `mcp-publisher login dns --private-key ...`.
# =============================================================================

set -euo pipefail

DOMAIN="${1:-greenhelix.net}"
KEY_FILE="${KEY_FILE:-key.pem}"

if [[ -e "${KEY_FILE}" ]]; then
  echo "ERROR: ${KEY_FILE} already exists. Move/delete it first." >&2
  exit 1
fi

echo ">> Generating Ed25519 key pair at ${KEY_FILE}..."
openssl genpkey -algorithm Ed25519 -out "${KEY_FILE}"

echo ""
echo "============================================================"
echo "Step 1 — Add the following TXT record to ${DOMAIN} DNS:"
echo "============================================================"
PUBLIC_KEY="$(openssl pkey -in "${KEY_FILE}" -pubout -outform DER | tail -c 32 | base64)"
echo "${DOMAIN}. IN TXT \"v=MCPv1; k=ed25519; p=${PUBLIC_KEY}\""

echo ""
echo "============================================================"
echo "Step 2 — Store the private key in GitHub as a secret:"
echo "============================================================"
PRIVATE_KEY="$(openssl pkey -in "${KEY_FILE}" -noout -text | grep -A3 "priv:" | tail -n +2 | tr -d ' :\n')"
echo "Secret name:  MCP_REGISTRY_PRIVATE_KEY"
echo "Secret value: ${PRIVATE_KEY}"
echo ""
echo "  gh secret set MCP_REGISTRY_PRIVATE_KEY --app actions --body \"${PRIVATE_KEY}\""
echo ""

echo "============================================================"
echo "Step 3 — Wait for DNS propagation (1-5 min typically):"
echo "============================================================"
echo "  dig +short TXT ${DOMAIN}"
echo ""

echo "============================================================"
echo "Step 4 — Verify login works locally:"
echo "============================================================"
echo "  mcp-publisher login dns --domain \"${DOMAIN}\" --private-key \"${PRIVATE_KEY}\""
echo ""

echo "Done. Keep ${KEY_FILE} safe — or delete it after copying the private"
echo "key into GitHub secrets; the workflow regenerates it from the secret."
