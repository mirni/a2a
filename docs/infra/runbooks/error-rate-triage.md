# Error Rate Triage Runbook

**Purpose:** Rapidly identify the root cause of an elevated 4xx/5xx rate
from the gateway and contain the blast radius.

**Audience:** On-call engineer.

**Pre-conditions:** Access to Grafana/metrics, SSH to prod host.

**Target:** identify the primary error class within 10 minutes of alert.

---

## 1. Triage matrix

| Error class | p(root-cause) | Jump to |
| --- | --- | --- |
| 500 on a specific route only | Code bug | §3 |
| 500 across all routes | DB/lock/OOM | §4 |
| 401 spike | Key compromise OR auth-service regression | §5 |
| 402 spike | Real user overdrafts OR cost bug | §6 |
| 429 spike | DoS OR rate-limit misconfig | §7 |
| 502 from Cloudflare | Gateway crashed OR network | §8 |
| 503 spike | Startup, shutdown, or DB-unavailable | §4 |

---

## 2. First 2 minutes

```bash
# 1. Overall health
curl -fsS https://api.greenhelix.net/v1/health | jq .

# 2. Error breakdown (last 5 min)
ssh a2a-prod
sudo journalctl -u a2a-gateway --since "5 minutes ago" | \
    grep -oE 'HTTP/1.[01]" [0-9]{3}' | sort | uniq -c | sort -rn | head

# 3. Top failing route
sudo journalctl -u a2a-gateway --since "5 minutes ago" | \
    grep -E ' 5[0-9]{2} ' | \
    grep -oE 'POST|GET|PUT|DELETE [^"]*' | sort | uniq -c | sort -rn | head

# 4. Top agent IDs with errors
sudo journalctl -u a2a-gateway --since "5 minutes ago" | \
    grep -E 'agent_id":"[^"]*"' | \
    grep -oE 'agent_id":"[^"]*"' | sort | uniq -c | sort -rn | head
```

---

## 3. 500 on specific route

```bash
# 1. Capture a sample stack trace
sudo journalctl -u a2a-gateway --since "10 minutes ago" | \
    grep -B 2 -A 20 "Traceback" | head -100 > /tmp/stacks.txt

# 2. Identify exception type
grep -E '^\w+Error|Exception' /tmp/stacks.txt | sort | uniq -c | sort -rn

# 3. If it is a known product exception (e.g. InsufficientCreditsError,
#    ToolValidationError) that is being returned as 500 instead of its
#    mapped status: add it to _PRODUCT_EXC_NAMES in gateway/src/app.py.
#    This is audit H1 fix territory.

# 4. If genuinely unknown: check recent commits
git -C /opt/a2a-gateway log --oneline -20

# 5. Mitigation: rollback if regression correlates with last deploy
#    (see rollback.md)
```

---

## 4. 500 across all routes

Most likely: DB contention, OOM, or container death.

```bash
# 1. Memory
free -m
sudo journalctl -u a2a-gateway --since "10 minutes ago" | grep -i "killed\|memory\|oom"

# 2. Disk
df -h /var /tmp

# 3. DB integrity
for f in /var/lib/a2a/*.db; do
  sqlite3 "$f" "PRAGMA integrity_check;" | head -1 | awk -v f="$f" '{print f, $0}'
done

# 4. Process count
sudo pgrep -c -f 'uvicorn.*a2a'  # should be 1 per worker

# 5. Open file count
sudo ls /proc/$(pgrep -f uvicorn.*a2a | head -1)/fd | wc -l

# 6. If OOM: restart, then increase MemoryLimit in
#    systemd/a2a-gateway.service (then tune workers/concurrency)
sudo systemctl restart a2a-gateway
```

---

## 5. 401 spike

```bash
# 1. Is it a single attacker?
sudo journalctl -u a2a-gateway --since "10 minutes ago" | \
    grep -E '401|invalid_key' | \
    grep -oE '"ip":"[^"]*"' | sort | uniq -c | sort -rn | head

# 2. If single IP: block at Cloudflare (IP Access Rules)
# 3. If multiple IPs but same pattern: credential-stuffing attack
#    → consider Cloudflare rate-limit rule on /v1/execute

# 4. If all real customers: auth-service regression
#    — rollback or check paywall.db integrity
```

---

## 6. 402 spike

```bash
# Real overdrafts or a cost calculation bug?

# 1. Sample a few 402 events
sudo journalctl -u a2a-gateway --since "10 minutes ago" | \
    grep '402' | head -5

# 2. Cross-reference wallet balances
#    (pick 3 agent IDs from the log)
for a in agent1 agent2 agent3; do
  sqlite3 /var/lib/a2a/billing.db \
    "SELECT agent_id, balance FROM wallets WHERE agent_id='$a';"
done

# 3. If balances look unexpectedly low: cost-calculation bug —
#    check pricing.json and gateway/src/deps/billing.py
#    then page the payments owner.
```

---

## 7. 429 spike

```bash
# 1. Distribution by IP
sudo journalctl -u a2a-gateway --since "10 minutes ago" | \
    grep -E 'rate_limit|429' | \
    grep -oE '"ip":"[^"]*"' | sort | uniq -c | sort -rn | head

# 2. Sample limits
curl -fsS -H "Authorization: Bearer $A2A_TEST_KEY" \
    https://api.greenhelix.net/v1/pricing -D /tmp/headers.txt -o /dev/null
grep -i -E 'X-RateLimit|Retry-After' /tmp/headers.txt

# 3. If DoS: escalate to Cloudflare WAF — add rate-limit rule
# 4. If config issue: check gateway.env RATE_LIMIT_* vars
```

---

## 8. 502 from Cloudflare

```bash
# 1. Is the origin up?
curl -fsS https://api.greenhelix.net/v1/health -o /dev/null -w "%{http_code}\n"

# 2. If 502 persists at origin: gateway crashed
sudo systemctl status a2a-gateway
# → follow gateway-restart.md

# 3. If origin returns 200 but Cloudflare returns 502:
#    network issue between Cloudflare and origin.
#    - Check CF dashboard → Analytics → Origin Errors
#    - Verify Cloudflare Tunnel (cloudflared) health if used
#    - docs/infra/CLOUDFLARE_HARDENING.md
```

---

## 9. Escalation

- Error rate > 5% for 10 min: page CTO
- Any P0 incident (data loss, security breach): follow
  `docs/policies/incident-response-plan.md`
- Stuck > 30 min on triage: consider rollback (`rollback.md`)

---

*Last reviewed: 2026-04-05. Owner: CTO. Review cadence: quarterly.*
