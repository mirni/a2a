# Incident Response Plan

**Version:** 1.0
**Effective date:** 2026-04-04
**Review cadence:** Annual (next review: 2027-04-04)
**Owner:** CTO

---

## 1. Purpose

This plan defines how the A2A Commerce Platform team detects, responds to, and recovers from security and availability incidents. All personnel with production access must be familiar with this plan.

---

## 2. Severity Classification

| Level | Criteria | Response Time | Examples |
|-------|----------|--------------|----------|
| **SEV1 — Critical** | Data breach, complete service outage, credential compromise | 15 min | Unauthorized data access, gateway down >5min, leaked API keys |
| **SEV2 — High** | Partial outage, degraded performance, failed security control | 1 hour | Single endpoint down, error rate >10%, failed auth bypass attempt |
| **SEV3 — Medium** | Non-critical issue, security warning, policy violation | 4 hours | Elevated error rate, dependency vulnerability, access anomaly |
| **SEV4 — Low** | Informational, minor misconfiguration | Next business day | Log anomaly, non-critical CVE, documentation gap |

---

## 3. Detection Sources

| Source | Alert Channel | Monitors |
|--------|--------------|----------|
| **Prometheus + Alertmanager** | Webhook (Slack/PagerDuty) | Gateway health, error rates, latency, disk usage |
| **Cloudflare** | Email / dashboard | WAF blocks, DDoS events, SSL issues |
| **GitHub Dependabot** | PR / email | Dependency vulnerabilities |
| **CI/CD Pipeline** | GitHub Actions | Failed security scans (bandit, semgrep, pip-audit) |
| **Admin Audit Log** | Application DB | Unauthorized admin access attempts |
| **External Reports** | Security email | Customer-reported issues, responsible disclosure |

---

## 4. Response Team & Escalation Matrix

| Role | Responsibility | Escalation Trigger |
|------|---------------|-------------------|
| **On-Call Engineer** | First responder; triage, initial containment | All alerts |
| **Incident Commander (CTO)** | Coordinates response; makes go/no-go decisions | SEV1, SEV2 |
| **Communications Lead** | Customer notification; status page updates | SEV1 with customer impact |

### Escalation Path

```
Alert fires
  → On-call engineer acknowledges (15 min SLA for SEV1)
    → If SEV1/SEV2: page Incident Commander
      → If data breach: engage legal counsel
        → If customer impact: activate Communications Lead
```

---

## 5. Response Phases

### 5.1 Detection & Triage

1. Acknowledge the alert
2. Assess severity using the classification table above
3. Open an incident tracking issue (GitHub Issues, label: `incident`)
4. Notify the response team per escalation matrix

### 5.2 Containment

Immediate actions by severity:

**SEV1 — Critical:**
- **Kill switch:** Disable compromised API keys via admin endpoint
- **Rate limit:** Apply emergency rate limiting (1 req/min global)
- **Firewall:** Block malicious IPs at Cloudflare WAF
- **Isolate:** If credential compromise, rotate all affected secrets immediately

**SEV2 — High:**
- **Circuit break:** Disable affected endpoint or tool
- **Rate limit:** Tighten rate limits for affected tier
- **Monitor:** Set up real-time dashboard for the specific issue

**SEV3/SEV4:**
- **Document:** Log the issue and monitoring data
- **Schedule:** Plan remediation for next work session

### 5.3 Eradication

1. Identify root cause (logs, metrics, code review)
2. Develop and test fix in staging environment
3. Deploy fix:
   - **Rollback:** `sudo dpkg -i /var/cache/a2a/a2a-gateway_<previous-version>.deb`
   - **Hot fix:** Emergency PR with expedited review (SEV1 only)
4. Verify fix resolves the issue without regression

### 5.4 Recovery

1. Restore normal operations (remove emergency rate limits, re-enable endpoints)
2. Verify all health checks pass
3. Monitor for recurrence (enhanced monitoring for 24-48 hours)
4. **Database restore** (if needed):
   ```bash
   # Stop service
   sudo systemctl stop a2a-gateway
   # Restore from latest backup
   cp /var/backups/a2a/<date>/*.db /var/lib/a2a/
   # Restart
   sudo systemctl start a2a-gateway
   ```

### 5.5 Communication

**Internal:**
- SEV1/SEV2: Real-time updates every 30 minutes during active incident
- All severities: Summary posted to incident tracking issue

**Customer-facing:**
- SEV1 with customer impact: Notify affected customers within 1 hour
- Status page update (if applicable)
- Post-incident summary within 48 hours

---

## 6. Post-Incident Review

Conduct a blameless post-incident review within 5 business days of SEV1/SEV2 incidents.

### Review Template

```markdown
# Post-Incident Review: [Incident Title]

**Date:** YYYY-MM-DD
**Severity:** SEV1/SEV2
**Duration:** HH:MM
**Incident Commander:** [Name]

## Timeline
- HH:MM — [Event]
- HH:MM — [Event]

## Root Cause
[Description of the underlying cause]

## Impact
- Services affected: [list]
- Customer impact: [description]
- Data impact: [none / description]

## What Went Well
- [Item]

## What Could Be Improved
- [Item]

## Action Items
| Action | Owner | Due Date | Status |
|--------|-------|----------|--------|
| [Action] | [Name] | YYYY-MM-DD | TODO |

## Lessons Learned
[Key takeaways for future prevention]
```

---

## 7. Runbooks

### 7.1 Gateway Down

**Symptoms:** `up{job="a2a-gateway"} == 0`, HTTP 502 from Cloudflare

```bash
# 1. Check service status
sudo systemctl status a2a-gateway

# 2. Check logs
sudo journalctl -u a2a-gateway --since "5 minutes ago" --no-pager

# 3. Check disk space
df -h /var/lib/a2a

# 4. Restart service
sudo systemctl restart a2a-gateway

# 5. If restart fails, rollback to previous version
sudo dpkg -i /var/cache/a2a/a2a-gateway_<previous>.deb
sudo systemctl restart a2a-gateway

# 6. Verify
curl -s https://api.greenhelix.net/v1/health | jq .
```

### 7.2 Credential Compromise

**Symptoms:** Unauthorized API calls, unknown admin actions in audit log

1. **Immediately** revoke compromised credentials
2. Rotate all secrets that may have been exposed:
   ```bash
   # Rotate JWT signing key
   # Rotate Stripe API keys (via Stripe dashboard)
   # Rotate admin key
   # Update .env / systemd credentials
   sudo systemctl restart a2a-gateway
   ```
3. Review audit logs for unauthorized actions
4. Notify affected customers if their API keys may be compromised
5. File incident report

### 7.3 Data Breach

**Symptoms:** Unauthorized data access confirmed

1. **Contain:** Isolate affected systems, revoke access
2. **Assess:** Determine scope of data exposed (which tables, time range)
3. **Legal:** Engage legal counsel for notification requirements
4. **Notify:** Affected customers within 72 hours (GDPR requirement if applicable)
5. **Remediate:** Fix vulnerability, rotate all credentials
6. **Document:** Full post-incident review with timeline

### 7.4 DDoS Attack

**Symptoms:** Traffic spike, elevated latency, Cloudflare alerts

1. **Cloudflare:** Enable "Under Attack" mode
2. **Rate limit:** Apply emergency rate limiting at gateway level
3. **Firewall:** Block offending IP ranges at Cloudflare WAF
4. **Monitor:** Watch traffic patterns for adaptation
5. **Escalate:** Contact Cloudflare support if mitigation insufficient

---

## 8. Testing

- **Tabletop exercise:** Quarterly (walk through a scenario without live action)
- **Failover drill:** Semi-annually (test backup restore, service rollback)
- **Full incident simulation:** Annually (live SEV2 scenario)

---

## 9. Contact Information

| Role | Contact Method |
|------|---------------|
| On-Call Engineer | [Configure in Alertmanager webhook] |
| CTO / Incident Commander | [Configure in Alertmanager webhook] |
| Cloudflare Support | https://dash.cloudflare.com/support |
| Stripe Support | https://support.stripe.com |
