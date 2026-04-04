# Secrets Management Policy

**Version:** 1.0
**Effective date:** 2026-04-04
**Review cadence:** Annual (next review: 2027-04-04)
**Owner:** CTO

---

## 1. Purpose

This policy defines how secrets (credentials, API keys, signing keys) are stored, accessed, rotated, and retired across the A2A Commerce Platform.

---

## 2. Current State

### 2.1 Storage Mechanism

Secrets are currently stored in `/opt/a2a/.env` and loaded via systemd `EnvironmentFile=`:

```ini
# /opt/a2a/.env (mode 0600, owner a2a:a2a)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
A2A_JWT_SECRET=...
A2A_ADMIN_KEY=...
GITHUB_DEPLOYMENT_TOKEN=...
```

### 2.2 Protections in Place

- File permissions: `0600` (owner-read only)
- Service user: `a2a` (unprivileged, no login shell)
- Systemd hardening: `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=yes`
- API keys hashed with SHA3-256 before database storage

---

## 3. Secret Classification

| Classification | Examples | Rotation Frequency | Compromise Response |
|---------------|----------|-------------------|-------------------|
| **Critical** | Stripe secret key, JWT signing key, admin key | 90 days | Immediate rotation, incident response |
| **Sensitive** | Database encryption keys, webhook secrets | 180 days | Rotate within 24h, audit access logs |
| **Internal** | GitHub deploy token, Cloudflare API token | 365 days | Rotate within 72h |

---

## 4. Rotation Procedures

### 4.1 Stripe Keys

1. Generate new key in Stripe Dashboard
2. Update `/opt/a2a/.env` (or systemd credential)
3. Restart gateway: `sudo systemctl restart a2a-gateway`
4. Verify payment flow in staging
5. Revoke old key in Stripe Dashboard

### 4.2 JWT Signing Key

1. Generate new key: `python -c "import secrets; print(secrets.token_hex(32))"`
2. Update `A2A_JWT_SECRET` in credential store
3. Restart gateway (existing JWTs will be invalidated)
4. Notify affected customers if in production

### 4.3 Admin Key

1. Generate new key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update `A2A_ADMIN_KEY` in credential store
3. Restart gateway
4. Update all admin tooling with new key

---

## 5. Migration Path: systemd LoadCredential

### 5.1 Target Architecture

Replace `.env` file with systemd `LoadCredential=` for each secret:

```ini
# In a2a-gateway.service [Service] section
LoadCredential=stripe_secret_key:/etc/credstore/a2a/stripe_secret_key
LoadCredential=stripe_webhook_secret:/etc/credstore/a2a/stripe_webhook_secret
LoadCredential=jwt_secret:/etc/credstore/a2a/jwt_secret
LoadCredential=admin_key:/etc/credstore/a2a/admin_key
```

Credentials are available to the service at `$CREDENTIALS_DIRECTORY/<name>`.

### 5.2 Application Code

The gateway uses `_get_secret()` in `gateway/src/lifespan.py` which checks `$CREDENTIALS_DIRECTORY` first, falling back to environment variables:

```python
def _get_secret(name: str, default: str | None = None) -> str | None:
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if cred_dir:
        path = os.path.join(cred_dir, name)
        if os.path.isfile(path):
            with open(path) as f:
                return f.read().strip()
    return os.environ.get(name, default)
```

### 5.3 Migration Steps

1. Create credential directory: `sudo mkdir -p /etc/credstore/a2a`
2. Set permissions: `sudo chmod 0700 /etc/credstore/a2a`
3. Create individual credential files (mode 0600)
4. Uncomment `LoadCredential=` lines in service unit
5. Test with `systemd-creds` encryption (optional, for encrypted-at-rest credentials)
6. Remove secrets from `.env` file
7. Restart and verify

### 5.4 Benefits

- Secrets are isolated per-service (not shared via environment)
- systemd enforces file ownership and access control
- Compatible with `systemd-creds encrypt` for at-rest encryption
- No third-party dependency (unlike Vault)

---

## 6. Prohibited Practices

- **Never** commit secrets to version control
- **Never** log secret values (even at DEBUG level)
- **Never** pass secrets as command-line arguments (visible in `ps` output)
- **Never** store secrets in world-readable files
- **Never** share secrets via unencrypted channels (email, chat)
- **Never** use the same secret across environments (staging vs production)

---

## 7. Audit & Monitoring

- Access to credential files is logged via Linux audit subsystem
- Secret usage failures are logged by the gateway (without revealing the secret value)
- Quarterly access review: verify only authorized personnel can access credential files
- CI pipeline checks: `bandit` and `semgrep` scan for hardcoded secrets

---

## 8. Incident Response

If a secret is suspected to be compromised:

1. **Immediately** rotate the affected secret (see Section 4)
2. Open a SEV1 incident (see `docs/policies/incident-response-plan.md`)
3. Audit all access logs for the compromised secret
4. Determine blast radius (what systems/data were accessible)
5. Notify affected parties per incident response plan
