# Operational Readiness — Backup, Runbooks, Monitoring

**Priority:** BLOCKER (B4) + Sprint (S3, S4, S5, S6, S9, S10)
**Source:** Market Readiness Audit 2026-04-01
**Effort:** 5-7 days

## Blockers (before GA)

### Automated Database Backup
- Cron `scripts/backup_db.sh` on a schedule (hourly minimum)
- Verify backup integrity on restore
- Alerting on backup failure

## Sprint Items (within 2 weeks post-launch)

### Runbooks (S3)
Create runbooks in `docs/infra/runbooks/` for:
- Gateway restart / rollback procedure
- Database recovery from backup
- Stripe webhook debugging
- High error rate triage
- Disk space emergency

### Incident Response Plan (S4)
- Escalation matrix
- Severity definitions (P1-P4)
- Communication templates

### Secure `/metrics` Endpoint (S5)
- Require auth or restrict to internal network
- Currently public — exposes Prometheus metrics to anyone

### Missing Alerts (S6)
Add to `monitoring/prometheus/alerts.yml`:
- Database connection failures
- Webhook delivery failures
- Auth failure spikes
- Wallet reconciliation drift
- Certificate expiry
- Backup job failures

### Prometheus HA (S9)
- Add second Prometheus instance or switch to remote storage (Thanos/Mimir)

### Log Aggregation (S10)
- Ship structured logs to central collector (Loki, ELK, or similar)
