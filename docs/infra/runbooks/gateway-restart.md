# Gateway Restart Runbook

**Purpose:** Safely restart the `a2a-gateway` service without losing in-flight
requests, after a config change, deploy, OOM, or memory-leak remediation.

**Audience:** On-call engineer.

**Pre-conditions:** SSH access + sudo on the target VPS.

---

## 1. When to restart

| Symptom | Restart? |
| --- | --- |
| Memory usage > 90% and climbing | Yes (restart now) |
| After a config file change (`/etc/a2a-gateway/gateway.env`) | Yes |
| After a hotfix .deb install | Yes (dpkg usually does this) |
| P95 latency 3x baseline for > 15 min with no DB cause | Yes (last resort) |
| Intermittent 502s from Cloudflare | Yes |
| Specific tool failing | **No** — diagnose the tool first |
| Database errors | **No** — see `db-recovery.md` |

---

## 2. Graceful restart (preferred)

```bash
ssh a2a-prod
sudo systemctl reload a2a-gateway
```

`reload` sends SIGHUP. The gateway drains in-flight requests for up to
30 seconds before exiting (see `systemd/a2a-gateway.service` →
`TimeoutStopSec=30`). A fresh uvicorn worker is then spawned.

Verify:

```bash
sudo systemctl status a2a-gateway --no-pager | head -10
curl -fsS https://api.greenhelix.net/v1/health | jq .status
```

Expected: `"ok"`, uptime resets to < 30s.

---

## 3. Hard restart (if graceful hangs)

If `reload` takes > 60s, force stop + start:

```bash
# 1. Pause traffic at Cloudflare (optional but recommended for > 10s outage)
#    Dashboard → Security → Under Attack Mode, OR add IP block rule

# 2. Stop
sudo systemctl stop a2a-gateway

# 3. Confirm no lingering workers
sudo pgrep -af 'uvicorn.*a2a'
# If any remain:
sudo pkill -9 -f 'uvicorn.*a2a'

# 4. Check DB files are released (no hanging transactions)
sudo lsof /var/lib/a2a/*.db 2>/dev/null

# 5. Start
sudo systemctl start a2a-gateway

# 6. Verify
sudo journalctl -u a2a-gateway --since "1 minute ago" | tail -20
curl -fsS https://api.greenhelix.net/v1/health
```

---

## 4. Post-restart smoke test

```bash
# Version + uptime
curl -fsS https://api.greenhelix.net/v1/health | jq '{status, version, uptime_seconds}'

# Auth check (should 401)
curl -sS https://api.greenhelix.net/v1/pricing -o /dev/null -w "%{http_code}\n"

# Tool call with a known-good test key
curl -fsS -H "Authorization: Bearer $A2A_TEST_KEY" \
    https://api.greenhelix.net/v1/pricing | jq '.tools | length'

# Metrics endpoint (from allow-listed IP)
curl -fsS https://api.greenhelix.net/v1/metrics | head -5
```

---

## 5. Common failure modes

| Symptom | Fix |
| --- | --- |
| `Address already in use` on start | Leftover worker: `sudo pkill -9 -f uvicorn.*a2a` |
| `SchemaVersionMismatchError` | Run migrations: `scripts/migrate_db.sh` |
| `RuntimeError: REFUSING TO BOOT: A2A_ENV=...` | Stripe key/env mismatch — fix `/etc/a2a-gateway/gateway.env` |
| Service starts then exits | `journalctl -u a2a-gateway -n 100` for traceback |
| 502 at Cloudflare, 200 locally | DNS/Cloudflare — check `docs/infra/CLOUDFLARE_HARDENING.md` |

---

## 6. If restart does not resolve the issue

Do **not** restart in a loop. If two restarts within 10 minutes don't
recover the service:

1. Open an incident (see `docs/policies/incident-response-plan.md`).
2. Capture the last 500 log lines: `journalctl -u a2a-gateway -n 500 > /tmp/gateway-logs.txt`.
3. Consider rollback: `docs/infra/runbooks/rollback.md`.

---

*Last reviewed: 2026-04-05. Owner: CTO. Review cadence: quarterly.*
