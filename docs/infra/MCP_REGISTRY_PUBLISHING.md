# Publishing to the Official MCP Registry

**Status:** Infrastructure ready. Human action required once to provision
the DNS key and TXT record. Subsequent releases are automatic via GitHub
Actions.

This document explains how Green Helix publishes its MCP server
(`net.greenhelix/mcp-server`) to the official
[MCP Registry](https://registry.modelcontextprotocol.io/) using
**DNS-based authentication**.

---

## Server identity

| Field              | Value                           |
|--------------------|---------------------------------|
| Server name        | `net.greenhelix/mcp-server`     |
| Auth method        | DNS TXT on `greenhelix.net`     |
| npm package        | `@greenhelix/mcp-server`        |
| PyPI package       | `a2a-mcp-server`                |
| `server.json` path | `sdk-ts/mcp-server/server.json` |

Name format is `net.greenhelix/*` because the registry requires
reverse-DNS for domain auth, and Green Helix's canonical domain is
`greenhelix.net`.

## Ownership verification

The registry validates that each listed artifact actually belongs to us:

* **npm**: `package.json` must have
  `"mcpName": "net.greenhelix/mcp-server"` — already set in
  `sdk-ts/mcp-server/package.json`.
* **PyPI**: the README (shipped as the long description) must contain
  `<!-- mcp-name: net.greenhelix/mcp-server -->` — already present in
  `products/mcp_server/README.md`.

If either package drops the marker in a future release, the registry
will refuse to publish.

---

## One-time setup (human action required)

### 1. Generate an Ed25519 signing key

Run the helper locally (requires `openssl`):

```bash
cd /tmp
/workdir/scripts/mcp_registry/generate_dns_key.sh greenhelix.net
```

The script prints:

1. A TXT record to add to `greenhelix.net`
2. A private-key hex string to store as a GitHub secret

### 2. Add the TXT record to DNS

Using your DNS provider (Cloudflare, Route 53, etc.), add:

```
Type:  TXT
Name:  @  (or greenhelix.net.)
Value: v=MCPv1; k=ed25519; p=<PUBLIC_KEY_BASE64>
TTL:   300
```

Verify propagation:

```bash
dig +short TXT greenhelix.net | grep MCPv1
```

### 3. Store the private key in GitHub

```bash
gh secret set MCP_REGISTRY_PRIVATE_KEY --app actions --body "<hex-string>"
```

Optionally override the domain via repo variable:

```bash
gh variable set MCP_REGISTRY_DOMAIN --body greenhelix.net
```

### 4. Create the `mcp-registry` GitHub environment

```bash
gh api -X PUT repos/mirni/a2a/environments/mcp-registry
```

(An environment lets us require manual approval for registry publishes
if we ever want to gate them.)

### 5. Delete the local `key.pem`

The private key is now in the GitHub secret. Delete the local copy:

```bash
rm -f /tmp/key.pem
```

---

## Publishing a new version

Once setup is complete, releases are fully automated:

1. Bump the version in `products/mcp_server/pyproject.toml`,
   `products/mcp_server/src/a2a_mcp_server/_version.py`,
   `sdk-ts/mcp-server/package.json`, and
   `sdk-ts/mcp-server/server.json` (both `version` and the
   nested `packages[*].version`).

2. Tag and push:

   ```bash
   git tag mcp-v0.1.0
   git push origin mcp-v0.1.0
   ```

   This triggers the **Publish MCP** workflow, which:
   - runs the Python + TypeScript test suites
   - publishes `a2a-mcp-server` to PyPI (trusted publishing, OIDC)
   - publishes `@greenhelix/mcp-server` to npm (with provenance)
   - verifies both installs end-to-end

3. On success, the **Publish MCP Registry** workflow fires
   automatically (via `workflow_run`), authenticates with DNS, and
   publishes `server.json` to the MCP Registry.

4. Verify the listing:

   ```bash
   curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=net.greenhelix/mcp-server"
   ```

---

## Troubleshooting

| Error                                              | Fix                                                                                                                        |
|----------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------|
| `DNS TXT record not found`                         | Wait a few more minutes, then check propagation from the GitHub runner network with `dig`.                                 |
| `Registry validation failed for package`           | Check `mcpName` in `package.json` and `mcp-name` marker in PyPI README still match `net.greenhelix/mcp-server`.            |
| `Invalid or expired Registry JWT token`            | Re-run `mcp-publisher login dns ...` locally to confirm the key still matches the TXT record; rotate if needed.            |
| `Missing environment variable MCP_REGISTRY_PRIVATE_KEY` | Re-add the GitHub secret — environment-scoped secrets are not inherited if the `mcp-registry` environment was deleted. |

---

## Rotating the signing key

If the private key leaks, rotate by:

1. Running `scripts/mcp_registry/generate_dns_key.sh` again.
2. Updating the TXT record (you can keep the old record for a grace
   period since the registry only needs one matching key).
3. Updating the `MCP_REGISTRY_PRIVATE_KEY` secret.
4. Removing the old TXT record after 24 hours.
