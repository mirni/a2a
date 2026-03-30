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

## Step 5: SSH key setup for GitHub Actions

Create a deploy key so GitHub Actions can SSH to the server:

```bash
# On your local machine
ssh-keygen -t ed25519 -f ~/.ssh/a2a-staging-deploy -N "" -C "github-actions-staging"

# Copy public key to the server
ssh-copy-id -i ~/.ssh/a2a-staging-deploy.pub root@SERVER

# Add the private key as a GitHub secret
# Go to Settings → Secrets → Actions → New repository secret
# Name: STAGING_SSH_KEY
# Value: contents of ~/.ssh/a2a-staging-deploy

# Also add the server host
# Name: STAGING_HOST
# Value: the server's IP or hostname
```

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
