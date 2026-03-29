# SOC 2 Type II Certification Plan — A2A Commerce Platform

## Overview

SOC 2 Type II certification demonstrates that the A2A Commerce Platform maintains effective controls over Security, Availability, and Confidentiality of customer data over a sustained period (typically 6-12 months).

**Target timeline:** Begin audit readiness Q3 2026, observation period Q4 2026-Q1 2027, report Q2 2027.

---

## Trust Service Criteria (TSC) Scope

We will pursue **Security**, **Availability**, and **Confidentiality** criteria. Processing Integrity and Privacy can be added later.

---

## Phase 1: Gap Assessment (Weeks 1-4)

### 1.1 Inventory current controls
- [ ] Map all data flows (agent data, payment data, API keys, audit logs)
- [ ] Document infrastructure topology (Ubuntu 24.04, SQLite/PostgreSQL, nginx, Cloudflare)
- [ ] Identify all third-party integrations (Stripe, Cloudflare, GitHub)
- [ ] Catalog all sensitive data stores and encryption status

### 1.2 Identify gaps against SOC 2 criteria
- [ ] Security: access controls, network segmentation, vulnerability management
- [ ] Availability: uptime SLA, disaster recovery, capacity planning
- [ ] Confidentiality: data classification, encryption at rest/transit, key management

### 1.3 Deliverable
- Gap assessment report with prioritized remediation items

---

## Phase 2: Policy & Procedure Development (Weeks 5-10)

### 2.1 Required policies
- [ ] **Information Security Policy** — scope, roles, responsibilities
- [ ] **Access Control Policy** — RBAC, least privilege, API key lifecycle
- [ ] **Incident Response Plan** — detection, containment, eradication, recovery, post-mortem
- [ ] **Change Management Policy** — PR reviews, CI/CD gates, deployment approval
- [ ] **Data Classification Policy** — public, internal, confidential, restricted
- [ ] **Business Continuity & Disaster Recovery Plan** — RTO/RPO targets, backup validation
- [ ] **Vendor Management Policy** — Stripe, Cloudflare, GitHub risk assessment
- [ ] **Employee/Contractor Security Policy** — onboarding, offboarding, training

### 2.2 Procedures
- [ ] Vulnerability scanning procedure (dependency audit, bandit, semgrep — already in CI)
- [ ] Penetration testing procedure (annual, by qualified third party)
- [ ] Log review procedure (who reviews Prometheus/Grafana alerts, frequency)
- [ ] Backup testing procedure (monthly restore test from SQLite backups)

---

## Phase 3: Technical Controls Implementation (Weeks 8-16)

### 3.1 Security controls
- [ ] **Encryption at rest:** Enable SQLite encryption (already have `encrypt_backup()` in db_security.py; extend to live DB or migrate to PostgreSQL with TDE)
- [ ] **Encryption in transit:** Verify TLS 1.2+ everywhere (Cloudflare → nginx → app). Document certificate rotation process.
- [ ] **API key management:** SHA3-256 hashing (already implemented). Add key rotation reminders, expiry policy.
- [ ] **Secrets management:** Move from `.env` files to a secrets manager (e.g., HashiCorp Vault, AWS Secrets Manager, or systemd credentials)
- [ ] **Network security:** UFW rules restricting port 443 to Cloudflare IPs (already in deploy.sh). Document firewall review cadence.
- [ ] **MFA enforcement:** Require MFA for all admin/operator access (SSH, Grafana, Cloudflare dashboard)

### 3.2 Availability controls
- [ ] **Monitoring & alerting:** Prometheus + Grafana (already deployed). Add PagerDuty/Opsgenie integration for GatewayDown, HighErrorRate alerts.
- [ ] **Uptime SLA:** Define and publish (e.g., 99.9% monthly for Pro/Enterprise tiers)
- [ ] **Backup & restore:** Automated daily SQLite backup (already in deploy.sh cron). Add monthly restore drill.
- [ ] **Capacity planning:** Document disk usage projections (60GB limit), set alerts at 70%/85%/95%.

### 3.3 Confidentiality controls
- [ ] **Data retention policy:** Implement audit log purge per tier retention (already coded: 7/30/90 days)
- [ ] **Data minimization:** Review what PII is collected; minimize to agent_id + API key hash
- [ ] **Access logging:** All admin actions logged to audit_log (extend from agent actions to operator actions)

---

## Phase 4: Evidence Collection & Automation (Weeks 12-20)

### 4.1 Continuous compliance tooling
- [ ] **Vanta, Drata, or Secureframe** — Automated SOC 2 evidence collection platform. Connects to GitHub, cloud infra, and ticketing.
- [ ] **CI/CD evidence:** GitHub Actions logs for all deployments (already exists)
- [ ] **Code review evidence:** GitHub PR review requirements (set up branch protection rules requiring 1+ approval)
- [ ] **Vulnerability evidence:** Automated dependency audit, bandit, semgrep reports (CI jobs — need to fix, currently failing)
- [ ] **Access review evidence:** Quarterly access review (who has SSH, API admin, Cloudflare access)

### 4.2 Logging & audit trail
- [ ] Structured logging with correlation IDs (already in middleware.py)
- [ ] Centralize logs (ship to ELK/Loki or cloud logging service)
- [ ] Retain logs for 1 year minimum
- [ ] Tamper-evidence: forward logs to write-once storage or sign log batches

---

## Phase 5: Pre-Audit Readiness (Weeks 18-22)

### 5.1 Internal audit
- [ ] Conduct mock SOC 2 audit against all criteria
- [ ] Remediate any findings
- [ ] Verify all policies have been followed for 30+ days

### 5.2 Select auditor
- [ ] Choose CPA firm experienced with tech startups (e.g., Schellman, A-LIGN, Prescient Assurance, Johanson Group)
- [ ] Budget: $15K-$40K for Type II depending on scope
- [ ] Schedule readiness assessment with auditor

---

## Phase 6: Observation Period (Months 6-12)

### 6.1 Operate under controls
- [ ] All policies enforced
- [ ] Evidence collected continuously via compliance platform
- [ ] Quarterly access reviews executed
- [ ] Monthly backup restore drills executed
- [ ] All incidents documented per IRP

### 6.2 Auditor fieldwork
- [ ] Provide auditor access to compliance platform
- [ ] Respond to auditor requests within SLA (typically 48h)
- [ ] Schedule management interviews

---

## Phase 7: Report & Maintenance

### 7.1 SOC 2 Type II report
- [ ] Review draft report with auditor
- [ ] Address any exceptions or qualifications
- [ ] Publish report availability to customers

### 7.2 Ongoing maintenance
- [ ] Annual re-certification
- [ ] Continuous monitoring of all controls
- [ ] Update policies as platform evolves

---

## Immediate Action Items (Start Now)

| Priority | Item | Owner | Status |
|----------|------|-------|--------|
| **P0** | Fix failing CI quality jobs (mypy, bandit, semgrep, dep audit) | Engineering | TODO |
| **P0** | Set up branch protection rules (require PR review) | Engineering | TODO |
| **P1** | Write Information Security Policy | CTO | TODO |
| **P1** | Write Incident Response Plan | CTO | TODO |
| **P1** | Set up secrets management (replace .env files) | Engineering | TODO |
| **P1** | Add alerting integration (PagerDuty/Opsgenie) to Grafana | Engineering | TODO |
| **P2** | Evaluate compliance platforms (Vanta vs Drata vs Secureframe) | CTO | TODO |
| **P2** | Select SOC 2 auditor and schedule readiness call | CTO | TODO |
| **P2** | Centralize log shipping | Engineering | TODO |
| **P3** | Implement MFA for all admin access | Engineering | TODO |
| **P3** | Document data flow diagrams | Engineering | TODO |

---

## Cost Estimate

| Item | Cost |
|------|------|
| Compliance platform (Vanta/Drata) | $10K-$15K/year |
| SOC 2 Type II audit (CPA firm) | $15K-$40K |
| Secrets management (if self-hosted Vault) | $0 (OSS) |
| Penetration test (annual) | $5K-$15K |
| Engineering time (controls implementation) | 2-4 weeks FTE |
| **Total Year 1** | **$30K-$75K** |

---

## References

- AICPA Trust Services Criteria (2017): https://www.aicpa.org/
- Existing platform controls: See `gateway/src/middleware.py` (correlation IDs, metrics), `products/shared/src/db_security.py` (encryption, hardening), `monitoring/` (Prometheus + Grafana)
