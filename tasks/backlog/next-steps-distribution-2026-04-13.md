# Next Steps: Distribution — Human Actions Required

**Date:** 2026-04-13
**Context:** MCP server code is complete and tested. Registry publish,
directory submissions, and CI secrets all require human credentials or
DNS access that the agent cannot perform.

---

## P0-1: MCP Registry DNS Verification

The MCP server (`net.greenhelix/mcp-server`) is built and tested.
Publishing to `registry.modelcontextprotocol.io` requires a one-time
DNS TXT record + GitHub secret. Full docs: `docs/infra/MCP_REGISTRY_PUBLISHING.md`.

### Steps

1. **Generate the Ed25519 signing key:**
   ```bash
   cd /tmp
   /workdir/scripts/mcp_registry/generate_dns_key.sh greenhelix.net
   ```
   Save the printed public key (base64) and private key (hex).

2. **Add DNS TXT record** in Cloudflare (greenhelix.net zone):
   ```
   Type:  TXT
   Name:  @
   Value: v=MCPv1; k=ed25519; p=<PUBLIC_KEY_BASE64>
   TTL:   300
   ```

3. **Verify propagation** (wait ~5 min):
   ```bash
   dig +short TXT greenhelix.net | grep MCPv1
   ```

4. **Store private key in GitHub:**
   ```bash
   source .env && export GH_TOKEN="$GITHUB_DEPLOYMENT_TOKEN"
   gh secret set MCP_REGISTRY_PRIVATE_KEY --app actions --body "<hex-string>"
   ```

5. **Create the `mcp-registry` environment:**
   ```bash
   gh api -X PUT repos/mirni/a2a/environments/mcp-registry
   ```

6. **Delete the local key:**
   ```bash
   rm -f /tmp/key.pem
   ```

7. **Trigger first publish:**
   ```bash
   git tag mcp-v0.1.0 && git push origin mcp-v0.1.0
   ```
   This triggers the Publish MCP workflow → PyPI + npm → MCP Registry.

8. **Verify listing:**
   ```bash
   curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=net.greenhelix/mcp-server"
   ```

---

## P0-2: mcp.so Submission

Submit via GitHub issue on `chatmcp/mcp-directory`:

```bash
gh issue create --repo chatmcp/mcp-directory \
  --title "Add net.greenhelix/mcp-server (A2A Commerce)" \
  --body "$(cat <<'EOF'
## Server Info
- **Name:** A2A Commerce Gateway MCP Server
- **Description:** 141-tool MCP server for AI agent commerce — payments, escrow, identity, marketplace, formal verification (Z3 Gatekeeper)
- **npm:** @greenhelix/mcp-server
- **PyPI:** a2a-mcp-server
- **GitHub:** https://github.com/mirni/a2a/tree/main/products/mcp_server
- **Category:** Commerce & Payments
EOF
)"
```

---

## P0-3: Glama Submission

1. Go to: https://glama.ai/mcp/servers (click "Add Server")
2. Fill in:
   - **Server URL:** `https://github.com/mirni/a2a/tree/main/products/mcp_server`
   - **npm package:** `@greenhelix/mcp-server`
   - **Description:** AI agent commerce platform — 141 tools for payments, escrow, identity, marketplace, and Z3 formal verification

---

## P0-6: a2aregistry.org + a2a.ac

### a2aregistry.org
1. Go to: https://a2aregistry.org/submit
2. Submit the agent card URL: `https://api.greenhelix.net/.well-known/agents.json`

### a2a.ac
1. Go to: https://a2a.ac/submit
2. Submit the same agent card URL

---

## STRESS_ADMIN_KEY Secret Setup

The production stress test (`scripts/stress_test.py`) silently skips
the Gatekeeper smoke check when `STRESS_ADMIN_KEY` is empty. All 387
requests return 401 → 100% error rate (falsely reported as PASS because
they're all auth errors).

### Steps

1. **Provision an admin API key on production:**
   ```bash
   curl -X POST https://api.greenhelix.net/v1/infra/keys \
     -H "Authorization: Bearer $ADMIN_KEY" \
     -H "Content-Type: application/json" \
     -d '{"agent_id": "ci-stress-agent", "tier": "pro"}'
   ```
   Save the returned `key` value.

2. **Add to GitHub Actions secrets:**
   ```bash
   source .env && export GH_TOKEN="$GITHUB_DEPLOYMENT_TOKEN"
   gh secret set STRESS_ADMIN_KEY --app actions --body "<key-from-step-1>"
   ```

3. **Verify** by re-running the stress test workflow. Expected: gatekeeper
   smoke check runs and shows `"Gatekeeper OK — Z3 job returned 'satisfied'"`,
   error rate drops from 100% to <5%.
