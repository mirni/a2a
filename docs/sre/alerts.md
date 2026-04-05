# SRE Alert Catalog

**Purpose:** authoritative map of every production alert — its trigger
condition, severity, owner, and runbook.

**Audience:** on-call engineer, SRE, CTO.

**Source of truth:** `monitoring/prometheus/alerts.yml`. This document
explains *why* each alert exists and *what to do* when it fires.

---

## Severity model

| Severity | Response time | Paging | Examples |
| --- | --- | --- | --- |
| **critical** | ≤ 15 min, 24/7 | pager + Slack | gateway down, data-loss risk, auth spike |
| **warning** | ≤ 1 business-hour | Slack | elevated latency, disk > 85%, backup lag |
| **info** | review next business day | Slack channel only | low-volume anomalies, trend breaks |

SLO breaches escalate to **critical** automatically; warnings that
persist for 30+ minutes escalate to **critical**.

---

## SLOs (Service Level Objectives)

| SLO | Target | Measurement window | Error budget |
| --- | --- | --- | --- |
| **Availability** (5xx rate) | 99.5% | 30 days | 3.6 h / 30d |
| **P95 latency** (`/v1/execute`) | < 500 ms | 7 days | — |
| **Payment success rate** | ≥ 99.9% | 7 days | — |
| **Webhook delivery** | ≥ 99% within 60s | 24 hours | — |
| **Backup success** | 100% nightly | 7 days | 0 miss |

Burn-rate alerts fire when error budget is being consumed at >10×
baseline for 1h, or >2× baseline for 6h.

---

## Alert catalog

### Gateway layer

#### `HighErrorRate` (critical)
- **Trigger:** `rate(a2a_errors_total[5m]) / rate(a2a_requests_total[5m]) > 0.05` for 2m
- **Meaning:** More than 5% of gateway requests returning 5xx.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/error-rate-triage.md`](../infra/runbooks/error-rate-triage.md)
- **Blast radius:** all customers
- **First action:** `§2` of error-rate-triage.md — identify top failing route in <2 min

#### `HighLatency` (warning)
- **Trigger:** avg request duration > 2000 ms for 3m
- **Meaning:** P50 latency is 4× normal baseline (~500 ms).
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/gateway-restart.md`](../infra/runbooks/gateway-restart.md) §1
- **First action:** check DB contention (`sqlite3 PRAGMA integrity_check;`) + memory

#### `GatewayDown` (critical) — paging
- **Trigger:** `up{job="a2a-gateway"} == 0` for 2m
- **Meaning:** Prometheus can't scrape metrics → gateway is unreachable or crashed.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/gateway-restart.md`](../infra/runbooks/gateway-restart.md)
- **Blast radius:** 100% of traffic
- **First action:** `systemctl status a2a-gateway` + `curl /v1/health`

---

### Application layer

#### `AuthFailureSpike` (critical) — paging
- **Trigger:** `rate(a2a_auth_failures_total[5m]) > 10` for 2m
- **Meaning:** > 10 auth failures/sec — credential stuffing or brute-force attempt.
- **Owner:** on-call + security
- **Runbook:** [`docs/infra/runbooks/error-rate-triage.md`](../infra/runbooks/error-rate-triage.md) §5
- **First action:** identify source IPs, block at Cloudflare if single-source

#### `DatabaseErrors` (critical)
- **Trigger:** `rate(a2a_db_errors_total[5m]) > 0` for 3m
- **Meaning:** sustained DB errors — lock contention, corruption, or disk-full.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/db-recovery.md`](../infra/runbooks/db-recovery.md)
- **First action:** `PRAGMA integrity_check` on each DB, `df -h`

#### `WebhookDeliveryFailures` (warning)
- **Trigger:** `rate(a2a_webhook_failures_total[5m]) > 0` for 5m
- **Meaning:** Outbound webhooks failing — customer integrations breaking.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/stripe-webhook-debug.md`](../infra/runbooks/stripe-webhook-debug.md) (inbound-oriented; outbound symptoms overlap)
- **First action:** inspect `webhooks.db` queue depth + sample destinations

#### `BackupFailure` (critical)
- **Trigger:** `a2a_backup_last_success_timestamp < time() - 86400` for 1h
- **Meaning:** No successful nightly backup in > 24 hours.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/db-recovery.md`](../infra/runbooks/db-recovery.md) §6
- **First action:** `systemctl status a2a-backup.timer` + `journalctl -u a2a-backup`

---

### Host / infrastructure layer

#### `HighCPU` (warning)
- **Trigger:** CPU > 80% for 5m
- **Meaning:** Host saturation — likely runaway worker or traffic spike.
- **Owner:** on-call engineer
- **First action:** `top`, identify offender, correlate with gateway logs

#### `HighMemory` (warning)
- **Trigger:** memory > 85% for 5m
- **Meaning:** Leak risk. If sustained, precedes OOM kill.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/gateway-restart.md`](../infra/runbooks/gateway-restart.md) §1 (OOM row)
- **First action:** `free -m`, `systemctl status a2a-gateway` for OOM events

#### `DiskSpaceLow` (critical)
- **Trigger:** disk < 15% free for 5m
- **Meaning:** Risk of write failures → DB corruption, backup misses.
- **Owner:** on-call engineer
- **Runbook:** [`docs/infra/runbooks/disk-emergency.md`](../infra/runbooks/disk-emergency.md)
- **First action:** journalctl vacuum, apt clean, old backup prune

---

## Proposed future alerts (not yet implemented)

These are SLO-derived alerts we plan to add as business volume grows:

- **`PaymentSuccessRateLow`** — `< 99.9%` captures over 5m → critical
- **`StripeWebhookLag`** — outbound Stripe acks > 5s average → warning
- **`WalletNegativeBalance`** — any wallet hits negative balance → critical (invariant)
- **`CertExpiringSoon`** — TLS cert < 14d remaining → warning

---

## Alertmanager routing

Current configuration (`monitoring/alertmanager/alertmanager.yml`):

```yaml
route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: slack-default
  routes:
    - match: { severity: critical }
      receiver: pagerduty
      continue: true
    - match: { severity: critical }
      receiver: slack-oncall
```

Critical alerts page the on-call (PagerDuty) **and** post to
`#a2a-oncall`. Warnings post only to `#a2a-ops`.

---

## Silencing & maintenance windows

Before any planned maintenance:

```bash
# Silence for 1 hour
amtool silence add alertname="GatewayDown" \
    --author="on-call" --comment="deploy v0.9.X" --duration=1h
```

Or via Alertmanager UI → `/#/silences`.

**Never silence a critical alert for more than 4 hours without CTO approval.**

---

## On-call handoff checklist

At shift start, the on-call engineer should:

1. Check Alertmanager UI for active/silenced alerts
2. Scan Grafana `gateway-overview` for anomalies
3. Review `/var/log/journal` for untriaged ERRORs
4. Confirm last nightly backup succeeded
5. Verify `journalctl -u a2a-gateway --since "24h ago" | grep -c ERROR` < 100

---

## Changelog

| Date | Change |
| --- | --- |
| 2026-04-05 | Initial catalog committed with 9 alerts + SLO map |

---

*Owner: CTO. Review cadence: quarterly.*
