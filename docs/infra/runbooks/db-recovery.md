# Database Recovery Runbook

**Purpose:** Restore the A2A gateway's SQLite databases after corruption,
accidental deletion, failed migration, or disk-full event.

**Audience:** On-call engineer, DBA, incident commander.

**Pre-conditions:** SSH + sudo on the affected host. Familiarity with SQLite.

---

## 1. Databases in use

All SQLite, under `/var/lib/a2a/` (prod) or `/tmp/a2a_gateway/` (dev):

| File | Product | Critical? |
| --- | --- | --- |
| `billing.db` | Wallets, transactions, usage, budgets | **CRITICAL** |
| `payments.db` | Intents, escrows, subscriptions, settlements | **CRITICAL** |
| `paywall.db` | API keys, rate limits | **CRITICAL** |
| `identity.db` | Agent identities, reputation, claims | HIGH |
| `marketplace.db` | Services, ratings, orgs | HIGH |
| `trust.db` | Trust scores | MEDIUM |
| `messaging.db` | Encrypted messages | MEDIUM |
| `event_bus.db` | Event log (rolling, 24h retention) | LOW |
| `webhooks.db` | Webhook delivery queue | LOW |
| `disputes.db` | Dispute tickets | HIGH |

Backups run nightly via cron → `/var/backups/a2a/YYYY-MM-DD/*.db`.

---

## 2. Detecting corruption

```bash
# Run on the host
for f in /var/lib/a2a/*.db; do
  echo "=== $f ==="
  sqlite3 "$f" "PRAGMA integrity_check;" | head -3
done
```

Expected: every DB returns `ok`. Any other output (e.g.
`*** in database main *** Page ... is never used`) indicates corruption.

Also check gateway logs:

```bash
journalctl -u a2a-gateway --since today | grep -i -E "OperationalError|disk I/O|malformed|integrity"
```

---

## 3. Recovery: restore from backup (preferred)

```bash
# 1. Stop gateway to release locks
sudo systemctl stop a2a-gateway

# 2. Pick newest complete backup
LATEST=$(ls -1t /var/backups/a2a/ | head -1)
echo "Restoring from: /var/backups/a2a/$LATEST"
ls -la /var/backups/a2a/$LATEST/

# 3. Move the corrupted DBs aside (do NOT delete — forensics)
sudo mkdir -p /var/lib/a2a/corrupted-$(date +%s)
sudo mv /var/lib/a2a/*.db /var/lib/a2a/corrupted-$(date +%s)/

# 4. Copy backup into place
sudo cp /var/backups/a2a/$LATEST/*.db /var/lib/a2a/
sudo chown a2a:a2a /var/lib/a2a/*.db
sudo chmod 0600 /var/lib/a2a/*.db

# 5. Verify integrity on restored files
for f in /var/lib/a2a/*.db; do
  echo "=== $f ==="
  sqlite3 "$f" "PRAGMA integrity_check;" | head -3
done

# 6. Start gateway
sudo systemctl start a2a-gateway

# 7. Verify health
curl -fsS https://api.greenhelix.net/v1/health | jq .
```

**Data loss:** up to 24 hours (since last nightly backup). Document this
in the incident report.

---

## 4. Recovery: .dump + .restore (corruption in non-critical rows)

If the corruption is isolated (e.g. a single row), try to recover the
schema + readable rows:

```bash
sudo systemctl stop a2a-gateway
cd /tmp
sudo cp /var/lib/a2a/payments.db payments.db.orig

# Dump what we can read
sqlite3 payments.db.orig ".dump" 2> dump-errors.txt > dump.sql
head dump-errors.txt  # review which rows failed

# Reload into a fresh DB
rm -f payments-recovered.db
sqlite3 payments-recovered.db < dump.sql

# Verify
sqlite3 payments-recovered.db "PRAGMA integrity_check;"
sqlite3 payments-recovered.db "SELECT COUNT(*) FROM payment_intents;"

# Install
sudo cp payments-recovered.db /var/lib/a2a/payments.db
sudo chown a2a:a2a /var/lib/a2a/payments.db
sudo chmod 0600 /var/lib/a2a/payments.db
sudo systemctl start a2a-gateway
```

---

## 5. Recovery: failed migration

```bash
# Symptom: app logs `SchemaVersionMismatchError: expected=7 actual=6`
# OR:       `OperationalError: no such column ...`

# 1. Stop service
sudo systemctl stop a2a-gateway

# 2. Run migration helper manually
cd /opt/a2a-gateway
sudo -u a2a HOME=/tmp python scripts/migrate_db.sh --dry-run
sudo -u a2a HOME=/tmp python scripts/migrate_db.sh

# 3. Verify version
sqlite3 /var/lib/a2a/billing.db "PRAGMA user_version;"

# 4. Start service
sudo systemctl start a2a-gateway
```

If migration fails mid-way: restore from backup (§3) then upgrade the
package again. Never edit `PRAGMA user_version` manually.

---

## 6. Disk full

```bash
# 1. Identify the full filesystem
df -h

# 2. Find offenders
sudo du -sh /var/lib/a2a/* 2>/dev/null | sort -h
sudo du -sh /var/log/* 2>/dev/null | sort -h | tail -5
sudo du -sh /var/backups/a2a/* 2>/dev/null | sort -h | tail -5

# 3. Prune old backups (keep last 14 days)
sudo find /var/backups/a2a/ -maxdepth 1 -type d -mtime +14 -exec rm -rf {} \;

# 4. Vacuum SQLite DBs (can reclaim 20-40%)
sudo systemctl stop a2a-gateway
for f in /var/lib/a2a/*.db; do
  sudo -u a2a sqlite3 "$f" "VACUUM;"
done
sudo systemctl start a2a-gateway

# 5. If still tight, rotate journalctl
sudo journalctl --vacuum-size=500M
```

See also `docs/infra/runbooks/disk-emergency.md`.

---

## 7. Post-recovery checks

```bash
# Balance invariants
sqlite3 /var/lib/a2a/billing.db "SELECT SUM(balance) FROM wallets;"
# Compare to: expected total credits ever issued - total withdrawals

# Payment intents consistency
sqlite3 /var/lib/a2a/payments.db \
  "SELECT status, COUNT(*) FROM payment_intents GROUP BY status;"

# Usage records
sqlite3 /var/lib/a2a/billing.db \
  "SELECT DATE(created_at, 'unixepoch'), COUNT(*) FROM usage_records
   GROUP BY 1 ORDER BY 1 DESC LIMIT 7;"
```

---

## 8. Escalation

- Data loss > 24h or missing transaction rows: notify CTO + CFO immediately
- Settlement discrepancy vs Stripe: contact Stripe support with intent IDs
- Cannot recover from backup: `docs/policies/incident-response-plan.md` §4

---

*Last reviewed: 2026-04-05. Owner: CTO. Review cadence: quarterly.*
