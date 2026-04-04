# Information Security Policy

**Version:** 1.0
**Effective date:** 2026-04-04
**Review cadence:** Annual (next review: 2027-04-04)
**Owner:** CTO

---

## 1. Purpose & Scope

This policy establishes the information security requirements for the A2A Commerce Platform, covering all systems, data, and personnel involved in the development, deployment, and operation of the platform.

**In scope:**
- A2A Gateway (API server, SQLite databases, systemd service)
- Monitoring stack (Prometheus, Grafana, Alertmanager, Loki)
- CI/CD pipeline (GitHub Actions, staging/production deployments)
- Third-party integrations (Stripe, Cloudflare, GitHub)
- All operator and developer access to production systems

**Out of scope:**
- Customer-side systems (agent implementations)
- End-user devices (beyond MFA requirements for operators)

---

## 2. Roles & Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **CTO** | Policy owner; final authority on security decisions; incident commander |
| **Engineering** | Implement technical controls; respond to alerts; maintain CI/CD security |
| **Operations** | Server administration; access provisioning/deprovisioning; backup validation |

All personnel with production access must:
- Complete security awareness onboarding
- Use MFA on all administrative interfaces (see `docs/policies/mfa-requirements.md`)
- Report suspected security incidents immediately

---

## 3. Asset Classification

| Classification | Description | Examples | Controls |
|---------------|-------------|----------|----------|
| **Restricted** | Credentials, signing keys | API master keys, Stripe secret keys, JWT signing keys | Encrypted at rest, never logged, rotate on compromise |
| **Confidential** | Customer data, payment data | Agent IDs, transaction records, billing data | Encrypted in transit + at rest, access-logged |
| **Internal** | Operational data | Prometheus metrics, deployment logs, CI artifacts | Access-controlled, retained per policy |
| **Public** | Published documentation | API docs, SDK, marketing site | No special controls |

---

## 4. Access Control

### 4.1 API Key Tiers

The platform uses tiered API keys with least-privilege access:

| Tier | Access Level | Rate Limits |
|------|-------------|-------------|
| **Free** | Basic tools only | 100 req/hr |
| **Pro** | All tools including billing, payments, identity | 1,000 req/hr |
| **Enterprise** | Full access + admin tools | 10,000 req/hr |

API keys are hashed with SHA3-256 before storage. Raw keys are never persisted.

### 4.2 Administrative Access

- **SSH:** Ed25519 key + TOTP required (see MFA policy)
- **Grafana:** Restricted to Tailscale network; Cloudflare Access or OIDC required
- **Cloudflare Dashboard:** TOTP or WebAuthn enforced at org level
- **GitHub:** Organization-enforced MFA

### 4.3 RBAC

Administrative operations are logged to the `admin_audit_log` table. All admin endpoints require `X-Admin-Key` authentication with constant-time comparison.

---

## 5. Network Security

### 5.1 Architecture

```
Internet → Cloudflare (WAF, DDoS, TLS termination)
         → nginx (reverse proxy, rate limiting)
         → A2A Gateway (127.0.0.1:8000)
```

### 5.2 Firewall (UFW)

- Port 443: Allow from Cloudflare IP ranges only
- Port 22: Allow from authorized IP ranges only
- Default: deny incoming, allow outgoing
- Review cadence: quarterly

### 5.3 Tailscale

Internal services (Grafana, Prometheus, staging) are accessible only via Tailscale mesh VPN. No public exposure.

---

## 6. Encryption

### 6.1 In Transit

- All external traffic: TLS 1.3 (enforced by Cloudflare)
- Internal service-to-service: localhost only (no network transit)
- Certificate management: Cloudflare-managed wildcard certificate

### 6.2 At Rest

- SQLite databases: `encrypt_backup()` for backup encryption (see `products/shared/src/db_security.py`)
- API keys: SHA3-256 one-way hash
- Secrets: systemd `LoadCredential=` (migration in progress from `.env` files)

---

## 7. Vulnerability Management

### 7.1 Automated Scanning (CI/CD)

Every PR and merge to `main` runs:

| Tool | Purpose |
|------|---------|
| **ruff** | Python linting and formatting |
| **mypy** | Static type checking |
| **bandit** | Python security linting |
| **semgrep** | SAST with community rules |
| **pip-audit** | Dependency vulnerability scanning |

### 7.2 Penetration Testing

- Frequency: Annual, by qualified third party
- Scope: External API surface, authentication, authorization
- Results: Documented in `tasks/external/`, remediated within SLA

### 7.3 Patch Management

- Python dependencies: Reviewed monthly, updated quarterly
- OS packages: `unattended-upgrades` enabled for security patches
- Zero-day response: Emergency patch within 24h for critical CVEs

---

## 8. Logging & Monitoring

- Structured JSON logging with correlation IDs (see `gateway/src/middleware.py`)
- Prometheus metrics: request rates, latencies, error rates, system health
- Grafana dashboards: real-time visibility
- Alertmanager: severity-based alerting with escalation
- Loki: centralized log aggregation with 90-day retention
- Audit trail: all admin actions logged to `admin_audit_log`

---

## 9. Incident Response

See `docs/policies/incident-response-plan.md` for the full incident response plan including severity classification, escalation matrix, and runbooks.

---

## 10. Compliance & Audit

- SOC 2 Type II certification: In progress (see `docs/infra/SOC2_CERTIFICATION_PLAN.md`)
- Internal security review: Quarterly
- Access review: Quarterly (all SSH, admin, and Cloudflare access)
- Policy review: Annual

---

## 11. Exceptions

Exceptions to this policy require written approval from the CTO with:
- Business justification
- Risk assessment
- Compensating controls
- Expiration date (maximum 90 days, renewable)

---

## 12. Enforcement

Violations of this policy may result in revocation of access privileges and disciplinary action.
