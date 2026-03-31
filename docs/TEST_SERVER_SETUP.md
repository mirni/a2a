# Test Server Setup — `test.greenhelix.net`

Guide for setting up the staging/test instance of the A2A gateway on the same
physical server as production. The test instance runs as a separate systemd
service on port 8001 with its own data directory.

## Architecture

```
Client → test.greenhelix.net → nginx (port 443)
                                  ↓
                          proxy_pass 127.0.0.1:8001
                                  ↓
                        a2a-gateway-test (uvicorn)
                                  ↓
                        /var/lib/a2a-test/*.db
```

Production and test run side by side:

| | Production | Test |
|---|---|---|
| Service | `a2a-gateway` | `a2a-gateway-test` |
| Port | 8000 | 8001 |
| Install dir | `/opt/a2a/` | `/opt/a2a-test/` |
| Data dir | `/var/lib/a2a/` | `/var/lib/a2a-test/` |
| .env | `/opt/a2a/.env` | `/opt/a2a-test/.env` |
| Domain | `api.greenhelix.net` | `test.greenhelix.net` |
| Deb package | `a2a-gateway` | `a2a-gateway-test` |

## Prerequisites

- Production server already provisioned (Ubuntu 22.04+, nginx, Python 3.12)
- DNS `A` record for `test.greenhelix.net` pointing to the server IP
- Cloudflare Origin certificate covering `test.greenhelix.net` (or use the
  existing wildcard `*.greenhelix.net` cert)

## Step 1: Install the test gateway package

```bash
# Build the test package locally
./scripts/create_package.sh a2a-gateway-test

# Copy to server and install
scp dist/a2a-gateway-test_0.3.0_all.deb root@SERVER:/tmp/
ssh root@SERVER 'dpkg -i /tmp/a2a-gateway-test_0.3.0_all.deb'
```

The `postinst` script automatically:
- Creates the `a2a` system user (if not already present)
- Creates `/var/lib/a2a-test/` and `/var/log/a2a-test/`
- Sets up a Python venv at `/opt/a2a-test/venv/`
- Creates `/opt/a2a-test/.env` with test-appropriate DSNs
- Creates and enables the `a2a-gateway-test` systemd service
- Starts the service on port 8001


## Step 3: Verify

```bash
# Check service status
systemctl status a2a-gateway-test

# Check health endpoint locally
curl http://127.0.0.1:8001/v1/health

# Check via nginx
curl https://test.greenhelix.net/v1/health
```

## Step 4: Configure `.env` (if needed)

Edit `/opt/a2a-test/.env` to add any connector API keys or other secrets
needed for staging tests. The default config uses SQLite databases in
`/var/lib/a2a-test/`.

## Step 5: Tailscale setup for GitHub Actions

The server is accessed via Tailscale (no public SSH port). GitHub Actions
uses the official `tailscale/github-action@v4` to join the tailnet as an
ephemeral node, then SSH to the server's Tailscale IP.

### 5a. Create a Tailscale OAuth client

1. Go to [Tailscale Admin Console → Settings → OAuth clients](https://login.tailscale.com/admin/settings/oauth)
2. Create a new OAuth client with the scope **`auth_keys`** (write)
3. Assign the tag **`tag:ci`** to the client (the CI runner will join as this tag)
4. Save the **Client ID** and **Client Secret**

### 5b. Enable Tailscale SSH on the server

On the server, enable Tailscale SSH so it accepts Tailscale-authenticated
connections without traditional SSH keys:

```bash
# Enable Tailscale SSH on the server
sudo tailscale up --ssh

# Verify Tailscale SSH is active
tailscale status
```

This tells the server to accept SSH connections authenticated via Tailscale
ACLs, bypassing the need for SSH keys or password auth.

### 5c. Configure Tailscale ACLs

In the [ACL editor](https://login.tailscale.com/admin/acls), allow `tag:ci`
to SSH to the server. Example:

```jsonc
{
  "tagOwners": {
    "tag:ci": ["autogroup:admin"]
  },
  "acls": [
    // ... existing rules ...
    {
      "action": "accept",
      "src": ["tag:ci"],
      "dst": ["YOUR-SERVER-HOSTNAME:*"]
    }
  ],
  "ssh": [
    // Allow CI runners to SSH as root to the server
    {
      "action": "accept",
      "src": ["tag:ci"],
      "dst": ["YOUR-SERVER-HOSTNAME"],
      "users": ["root"]
    }
  ]
}
```

**Important:** The `ssh` ACL section is what allows `tag:ci` nodes to SSH
as root. Without this, even with `tailscale up --ssh` on the server,
CI runners will get "Permission denied".

### 5d. Add GitHub repository secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Value |
|--------|-------|
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth Client ID |
| `TS_OAUTH_SECRET` | Tailscale OAuth Client Secret |
| `TAILSCALE_IP` | Server's Tailscale IP (e.g. `100.x.y.z`) |

Find the server's Tailscale IP with `tailscale ip -4` on the server, or
check the [Machines page](https://login.tailscale.com/admin/machines).

## Logs and Troubleshooting

```bash
# View test gateway logs
journalctl -u a2a-gateway-test -f

# Check nginx error log
tail -f /var/log/nginx/error.log

# Restart test instance
systemctl restart a2a-gateway-test

# Check which port is being used
ss -tlnp | grep 8001
```

## Upgrading

To upgrade the test gateway:

```bash
# Build new package
./scripts/create_package.sh a2a-gateway-test

# Deploy
scp dist/a2a-gateway-test_*.deb root@SERVER:/tmp/
ssh root@SERVER 'dpkg -i /tmp/a2a-gateway-test_*.deb'
```

The `prerm` script stops the service, `postinst` re-provisions and restarts it.
This is also what the staging CI workflow does automatically on every PR.
