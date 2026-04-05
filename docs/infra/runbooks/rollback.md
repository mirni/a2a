# Rollback Runbook

**Purpose:** Safely roll a production or staging deployment back to a prior
release when a newly deployed package is causing customer-visible errors,
regressions, or security incidents.

**Audience:** On-call engineer, incident commander.

**Pre-conditions:** You have SSH access to the affected VPS and sudo rights.

---

## 1. When to roll back

Roll back **immediately** if any of these are observed within 30 minutes of a
deploy:

- Error rate > 5% on `/v1/*` endpoints (check Grafana "Gateway Errors" panel)
- Any 500s from `/v1/execute`, `/v1/billing/*`, or `/v1/payments/*`
- Webhook signature verification failing on Stripe callbacks
- Database migration failures on startup (`SchemaVersionMismatchError`)
- Health check (`/v1/health`) returning non-200 for > 60 seconds
- Tool oracle regression: valid tool names returning `unknown_tool`

Do **not** roll back for:
- Known-flaky downstream (Stripe API incident) — check status.stripe.com first
- Latency spikes < 2x baseline without error-rate impact (wait 10 min first)

---

## 2. Identify previous working version

```bash
# On the affected host
dpkg -l | grep a2a-gateway
# Or: systemctl status a2a-gateway | grep Version
```

Find the prior `.deb` in `/var/cache/apt/archives/` or pull it from the
GitHub release assets:

```bash
# List recent releases
gh release list --repo mirni/a2a --limit 5

# Download a specific prior release asset
gh release download v0.9.5 --repo mirni/a2a --pattern '*.deb' -D /tmp/rollback/
```

---

## 3. Rollback steps (5–10 min)

### 3.1 Production gateway (`api.greenhelix.net`)

```bash
# 1. Pause traffic at Cloudflare (optional, only if rollback will take > 2 min)
#    — toggle "Under Attack Mode" OR enable "IP Access Rules" to limit traffic.
#    This is OPTIONAL. Skip if downtime is more costly than brief errors.

# 2. SSH to prod host
ssh a2a-prod

# 3. Verify current version
dpkg -l | grep a2a-gateway
systemctl status a2a-gateway --no-pager | head -5

# 4. Stop the service cleanly
sudo systemctl stop a2a-gateway

# 5. Install prior .deb (downgrade)
sudo dpkg -i /tmp/rollback/a2a-gateway_0.9.5_all.deb
#   ^-- replace version with the target rollback version.

# 6. If dpkg complains about "downgrade refused" use --force-downgrade:
sudo dpkg -i --force-downgrade /tmp/rollback/a2a-gateway_0.9.5_all.deb

# 7. Restart the service
sudo systemctl start a2a-gateway
sudo systemctl status a2a-gateway --no-pager | head -10

# 8. Verify health
curl -fsS https://api.greenhelix.net/v1/health | jq .
# Expected: {"status":"ok", "version":"0.9.5", ...}

# 9. Re-enable Cloudflare if you paused traffic.
```

### 3.2 Staging gateway (`test.greenhelix.net` / `sandbox.greenhelix.net`)

Same as 3.1 but SSH to the staging/sandbox host and install the
`a2a-gateway-test` or `a2a-gateway-sandbox` package.

### 3.3 Website (`greenhelix.net`)

```bash
ssh a2a-web
dpkg -l | grep a2a-website
sudo dpkg -i --force-downgrade /tmp/rollback/a2a-website_0.9.5_all.deb
sudo systemctl reload nginx
curl -fsS https://greenhelix.net/ -o /dev/null -w "%{http_code}\n"
```

---

## 4. Database migration safety

**Current policy:** migrations are **forward-only**. A rollback to an older
package against a newer DB schema may succeed because:

1. The app checks `PRAGMA user_version` on startup and accepts
   `db_version >= expected_version` (see `scripts/migrate_db_helper.py`).
2. Any new columns added by a forward migration are ignored by old code.

**Failure modes (manual recovery required):**

- **Removed columns:** if a migration dropped a column the old code still
  uses, old code will crash at query time. In this case restore from
  backup: `scripts/restore_database.sh <backup-file>`.
- **Changed column semantics:** if a migration changed a column's meaning
  (e.g. currency precision), both reads and writes may corrupt data.
  **Do not roll back without a DB restore.**

**Before any rollback:** check the commit log of the migrations directory
for breaking changes between the current and target versions:

```bash
git log --oneline products/*/src/migrations/ scripts/migrate_db.sh \
    v0.9.5..v0.9.6
```

If the list contains DROP/ALTER statements, **restore the DB from backup
before starting the old service**:

```bash
sudo systemctl stop a2a-gateway
sudo cp /var/backups/a2a/$(ls -1t /var/backups/a2a | head -1)/*.db /var/lib/a2a/
sudo chown a2a:a2a /var/lib/a2a/*.db
sudo chmod 0600 /var/lib/a2a/*.db
sudo dpkg -i --force-downgrade /tmp/rollback/a2a-gateway_0.9.5_all.deb
sudo systemctl start a2a-gateway
```

---

## 5. Post-rollback verification

Run these checks within 5 minutes of rollback completion:

```bash
# 1. Version
curl -fsS https://api.greenhelix.net/v1/health | jq -r .version

# 2. Exercise a handful of endpoints (use a valid test key)
export A2A_API_KEY=<test-key>
curl -fsS -H "X-API-Key: $A2A_API_KEY" \
    https://api.greenhelix.net/v1/pricing | jq '.tools | length'

# 3. Smoke-test a tool call
curl -fsS -XPOST -H "X-API-Key: $A2A_API_KEY" \
    -H "Content-Type: application/json" \
    -d '{"tool":"get_balance","params":{"agent_id":"<your-agent>"}}' \
    https://api.greenhelix.net/v1/execute | jq .

# 4. Check error rate in Grafana (should return to baseline within 5 min)

# 5. Verify Stripe webhooks still work
# Send a test event via Stripe Dashboard → "Send test webhook"
```

---

## 6. After the rollback

1. **Freeze deploys** — lock `main` or pause the deploy workflow until root
   cause is understood.
2. **Open an incident doc** — create `docs/infra/incidents/<date>.md`
   referencing this rollback, symptoms, affected time window, customers
   impacted, and next steps.
3. **Post-mortem** — schedule within 24h; owner = on-call engineer. Use
   `docs/policies/incident-response-plan.md` template.
4. **Fix-forward PR** — never re-deploy the same broken build. Fix the bug,
   add a regression test, cut a new point release.

---

## 7. Emergency contacts

- **Incident Commander:** CTO
- **Payments/Stripe escalation:** CFO + Stripe support (via dashboard)
- **Infra/DNS:** see `docs/infra/INFRA.md`
- **Security breach:** see `docs/policies/incident-response-plan.md` §4

---

*Last reviewed: 2026-04-05. Owner: CTO. Review cadence: quarterly or after
any rollback event.*
