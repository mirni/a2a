# Disk Emergency Runbook

**Purpose:** Recover from a full or near-full disk on a gateway/website host
without losing customer data.

**Audience:** On-call engineer.

**Pre-conditions:** SSH + sudo. Alerting has fired at ≥85% disk use.

**Time budget:** free 1+ GB within 10 minutes.

---

## 1. Immediate triage

```bash
ssh a2a-prod
df -h
# Locate the full mount (usually /)

sudo du -xh --max-depth=1 / 2>/dev/null | sort -h | tail -10
```

Most common offenders, in order:

1. `/var/log/journal` (systemd logs)
2. `/var/backups/a2a` (nightly DB snapshots)
3. `/var/lib/a2a` (live SQLite DBs — do NOT delete)
4. `/var/cache/apt` (apt package cache)
5. `/tmp` (runtime temp files)
6. `/home/<user>/.*` (caches, build artifacts)

---

## 2. Safe quick wins

### 2.1 journalctl (usually biggest win)

```bash
# See current journal size
sudo journalctl --disk-usage

# Keep last 7 days or 500 MB, whichever is smaller
sudo journalctl --vacuum-time=7d
sudo journalctl --vacuum-size=500M
```

### 2.2 apt cache

```bash
sudo apt-get clean       # removes downloaded .deb files
sudo apt-get autoremove  # removes orphaned packages
```

### 2.3 Old backups

Keep last 14 days of DB backups:

```bash
ls -lh /var/backups/a2a/ | sort -k6 | tail -20
sudo find /var/backups/a2a/ -maxdepth 1 -type d -mtime +14 -exec rm -rf {} \;
```

### 2.4 Temp files

```bash
sudo find /tmp -type f -atime +7 -delete
sudo find /var/tmp -type f -atime +14 -delete
```

---

## 3. If still full: SQLite vacuum

SQLite does not reclaim free pages until VACUUM runs. Can recover 20-40%.

```bash
# Service MUST be stopped (VACUUM needs exclusive lock)
sudo systemctl stop a2a-gateway

# Check sizes before
ls -lh /var/lib/a2a/*.db

# Vacuum each DB
for f in /var/lib/a2a/*.db; do
  echo "VACUUMing $f..."
  sudo -u a2a sqlite3 "$f" "VACUUM;"
done

# Check sizes after
ls -lh /var/lib/a2a/*.db

# Restart
sudo systemctl start a2a-gateway
curl -fsS https://api.greenhelix.net/v1/health | jq .status
```

**Downtime:** 30-90 seconds per DB, depending on size. Schedule during
low-traffic window if possible, but in an emergency just do it.

---

## 4. Still tight: trim event_bus / rotate tables

Event bus keeps 24h of events by default but may have grown:

```bash
sudo systemctl stop a2a-gateway
sudo -u a2a sqlite3 /var/lib/a2a/event_bus.db \
    "DELETE FROM events WHERE created_at < strftime('%s','now') - 86400;"
sudo -u a2a sqlite3 /var/lib/a2a/event_bus.db "VACUUM;"
sudo systemctl start a2a-gateway
```

Webhook delivery queue (keep only failed + recent):

```bash
sudo -u a2a sqlite3 /var/lib/a2a/webhooks.db \
    "DELETE FROM deliveries WHERE status='delivered' AND created_at < strftime('%s','now') - 86400*7;"
sudo -u a2a sqlite3 /var/lib/a2a/webhooks.db "VACUUM;"
```

Usage records (rollups are retained in hot/warm/cold tiers — but you can
trim the hot tier aggressively if needed):

```bash
sudo -u a2a sqlite3 /var/lib/a2a/billing.db \
    "DELETE FROM usage_records WHERE created_at < strftime('%s','now') - 86400*30;"
# (default lifecycle already handles this; only run manually if emergency)
sudo -u a2a sqlite3 /var/lib/a2a/billing.db "VACUUM;"
```

---

## 5. Expand the disk

If you cannot get below 85% with cleanup, add storage:

### Cloud provider (LXC/VPS)

1. Snapshot the disk (DO THIS FIRST — never resize without a snapshot)
2. In provider dashboard: resize to +20 GB
3. On host:
   ```bash
   sudo growpart /dev/sda 1
   sudo resize2fs /dev/sda1
   df -h
   ```

### Add a secondary volume for backups

```bash
# After attaching /dev/sdb in the console
sudo mkfs.ext4 /dev/sdb
sudo mkdir -p /mnt/backups
sudo mount /dev/sdb /mnt/backups
# Move backups
sudo systemctl stop a2a-backup.timer 2>/dev/null || true
sudo rsync -aP /var/backups/a2a/ /mnt/backups/a2a/
sudo rm -rf /var/backups/a2a
sudo ln -s /mnt/backups/a2a /var/backups/a2a
# Persist
echo "/dev/sdb /mnt/backups ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
```

---

## 6. Prevention

- Alert at 75% (warn) and 85% (critical) — see `monitoring/`.
- Backup retention: 14 days. Verify cleanup job runs.
- Journal limit: set `SystemMaxUse=1G` in `/etc/systemd/journald.conf`.
- Nightly VACUUM on low-traffic window (scheduled via cron).

---

## 7. Escalation

- Cannot free enough space in 15 min → CTO
- Data loss during cleanup (accidental `rm` of live DB) → §3 of
  `db-recovery.md`
- Disk hardware failure signs (dmesg I/O errors) → provider support

---

*Last reviewed: 2026-04-05. Owner: CTO. Review cadence: quarterly.*
