# Litestream Setup & Recovery Runbook

**Audience:** SRE / on-call
**Scope:** Continuous replication of A2A SQLite databases to S3 via
[Litestream](https://litestream.io).
**RPO:** < 1 minute (WAL shipped continuously).
**RTO:** < 15 minutes (`litestream restore` per db).

---

## Why this exists

A2A runs on SQLite files on a single host. Nightly `a2a-db-backup` snapshots
give us point-in-time copies (RPO: 1 hour, RTO: ~10 min), but a drive failure
between snapshots would lose up to an hour of transactions. Litestream closes
that gap by streaming the WAL to S3 as it is written, yielding near-zero data
loss with essentially no runtime overhead on the app.

Litestream is **additive** to `a2a-db-backup`. Do not disable one to save
cost — they cover different failure modes:

| Failure | Recovery tool |
|---|---|
| Corrupted row / accidental `DELETE` | `a2a-db-backup` (hourly snapshot → `/var/backups/a2a`) |
| Disk failure, host loss | Litestream (`litestream restore` from S3) |
| Region-wide outage | Litestream + restore in another region |
| Data loss between hourly snapshots | Litestream |

## Install

```bash
# 1. Install the upstream litestream binary
curl -L https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.deb -o /tmp/litestream.deb
sudo apt install /tmp/litestream.deb

# 2. Install the A2A config + systemd unit
sudo apt install ./dist/a2a-litestream_1.2.4_all.deb

# 3. Fill in credentials
sudo nano /etc/default/litestream-a2a
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# AWS_REGION=us-east-1
# LITESTREAM_BUCKET=a2a-litestream-prod

# 4. Start
sudo systemctl start litestream-a2a
sudo systemctl status litestream-a2a
```

## S3 bucket setup

One-time, in `us-east-1`:

```bash
aws s3api create-bucket --bucket a2a-litestream-prod --region us-east-1
aws s3api put-bucket-versioning --bucket a2a-litestream-prod \
    --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket a2a-litestream-prod \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# Lifecycle: expire non-current versions after 30 days
aws s3api put-bucket-lifecycle-configuration --bucket a2a-litestream-prod \
    --lifecycle-configuration file://lifecycle.json
```

IAM policy for the `litestream` IAM user (least privilege):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::a2a-litestream-prod",
        "arn:aws:s3:::a2a-litestream-prod/*"
      ]
    }
  ]
}
```

## Databases replicated

All listed in `/etc/litestream/litestream-a2a.yml`:

- `/var/lib/a2a/paywall.db`
- `/var/lib/a2a/payments.db`
- `/var/lib/a2a/gatekeeper.db`
- `/var/lib/a2a/trust.db`
- `/var/lib/a2a/identity.db`
- `/var/lib/a2a/audit.db`

Each replicates to `s3://a2a-litestream-prod/<product>/` with 5-minute
snapshots and 24-hour WAL retention.

## Verify replication is healthy

```bash
# Tail the journal
sudo journalctl -u litestream-a2a -f

# Expected output every few seconds:
# level=INFO msg=sync db=/var/lib/a2a/paywall.db position=0000000a/00002000

# Check last snapshot time in S3
sudo -u a2a litestream snapshots -config /etc/litestream/litestream-a2a.yml /var/lib/a2a/paywall.db
```

Alert if any of these are true:

- `journalctl -u litestream-a2a --since "5 minutes ago"` contains `error`.
- `litestream snapshots` last timestamp is > 10 minutes old.
- `systemctl is-active litestream-a2a` != `active`.

Wire these into `gateway/src/monitoring/` or Cloudwatch as desired.

## Recovery — full host loss

1. Provision a new host, install `a2a-gateway`, `a2a-litestream`.
2. Stop gateway: `sudo systemctl stop a2a-gateway`
3. Restore each db **before** starting the gateway:

    ```bash
    for db in paywall payments gatekeeper trust identity audit; do
        sudo -u a2a litestream restore \
            -config /etc/litestream/litestream-a2a.yml \
            -o /var/lib/a2a/${db}.db \
            /var/lib/a2a/${db}.db
    done
    ```

4. Verify row counts against the most recent `a2a-db-backup` snapshot:

    ```bash
    sudo -u a2a sqlite3 /var/lib/a2a/payments.db "SELECT COUNT(*) FROM payment_intents;"
    ```

5. Start litestream, then the gateway:

    ```bash
    sudo systemctl start litestream-a2a
    sudo systemctl start a2a-gateway
    ```

6. Smoke-test via `/health` + one read endpoint.

## Recovery — single corrupted db

Point-in-time restore, restoring *only* the damaged db while everything else
keeps serving:

```bash
# 1. Stop the gateway
sudo systemctl stop a2a-gateway

# 2. Back up the corrupted file to a forensic copy
sudo mv /var/lib/a2a/paywall.db /var/lib/a2a/paywall.db.broken-$(date +%s)

# 3. Restore to a specific timestamp (UTC)
sudo -u a2a litestream restore \
    -config /etc/litestream/litestream-a2a.yml \
    -timestamp "2026-04-10T14:30:00Z" \
    -o /var/lib/a2a/paywall.db \
    /var/lib/a2a/paywall.db

# 4. Integrity check
sudo -u a2a sqlite3 /var/lib/a2a/paywall.db "PRAGMA integrity_check;"

# 5. Restart gateway
sudo systemctl start a2a-gateway
```

## Gotchas

- **WAL mode required**: all A2A dbs already run in WAL mode (see
  `products/*/src/storage.py`). Litestream requires it.
- **Never rsync a live db**: the whole point of Litestream is to avoid
  tearing during copy. If you need an ad-hoc copy, run
  `sqlite3 source 'VACUUM INTO target'` on the running db.
- **systemd ReadWritePaths**: the unit grants `/var/lib/a2a`. If you add
  a new db outside that directory the unit will not be able to read it.
- **Do not commit `/etc/default/litestream-a2a`** — it contains AWS keys.
- **Cost**: 6 dbs × ~10 MB WAL/hr × 24 h = ~1.5 GB/day S3 storage. With
  30-day versioning retention, budget ~45 GB/month in `us-east-1`
  (< $1/month). The PUT request count dominates: ~1 per WAL segment,
  so ~10k/day = $0.05/day.

## Rollback

```bash
sudo systemctl stop litestream-a2a
sudo systemctl disable litestream-a2a
sudo apt remove a2a-litestream
```

The app continues to run — Litestream is observation-only; removing it
does not touch the dbs.
