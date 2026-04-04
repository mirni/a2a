# Multi-Factor Authentication (MFA) Requirements

**Version:** 1.0
**Effective date:** 2026-04-04
**Review cadence:** Annual (next review: 2027-04-04)
**Owner:** CTO

---

## 1. Purpose

All administrative and operator access to A2A Commerce Platform systems must use multi-factor authentication (MFA). This policy defines MFA requirements per system.

---

## 2. Per-System Requirements

### 2.1 SSH Access (Production Server)

| Factor | Requirement |
|--------|------------|
| **Primary** | Ed25519 SSH key (password authentication disabled) |
| **Second factor** | TOTP via `libpam-google-authenticator` or equivalent |
| **Key length** | Ed25519 (256-bit, equivalent to ~128-bit symmetric) |
| **Key passphrase** | Required (enforced by policy, not technically) |

**Configuration:**
```bash
# /etc/ssh/sshd_config
PubkeyAuthentication yes
PasswordAuthentication no
ChallengeResponseAuthentication yes
AuthenticationMethods publickey,keyboard-interactive
UsePAM yes
```

### 2.2 Grafana (Monitoring Dashboard)

| Factor | Requirement |
|--------|------------|
| **Primary** | Username + password |
| **Second factor** | Cloudflare Access (Zero Trust) or OIDC provider with MFA |
| **Network restriction** | Accessible only via Tailscale VPN |

**Options (choose one):**
- **Cloudflare Access:** Place Grafana behind Cloudflare Access with identity provider (Google/GitHub) that enforces MFA
- **OIDC:** Configure Grafana's built-in OIDC with a provider that enforces MFA (e.g., Google Workspace, Okta)

### 2.3 Cloudflare Dashboard

| Factor | Requirement |
|--------|------------|
| **Primary** | Email + password |
| **Second factor** | TOTP or WebAuthn (hardware key preferred) |
| **Enforcement** | Organization-level mandatory MFA |

Enable via: Cloudflare Dashboard > Settings > Authentication > Require 2FA for all members.

### 2.4 GitHub (Code & CI/CD)

| Factor | Requirement |
|--------|------------|
| **Primary** | Username + password or SSH key |
| **Second factor** | TOTP, WebAuthn, or GitHub Mobile |
| **Enforcement** | Organization-level mandatory MFA |

Enable via: GitHub Org Settings > Authentication security > Require two-factor authentication.

### 2.5 Stripe Dashboard

| Factor | Requirement |
|--------|------------|
| **Primary** | Email + password |
| **Second factor** | TOTP or SMS (TOTP preferred) |
| **Enforcement** | Team-level mandatory MFA |

---

## 3. Approved MFA Methods

| Method | Security Level | Approved For |
|--------|---------------|-------------|
| **WebAuthn / Hardware key** (YubiKey, etc.) | Highest | All systems |
| **TOTP** (authenticator app) | High | All systems |
| **Push notification** (GitHub Mobile) | Medium | GitHub only |
| **SMS** | Low (SIM swap risk) | Not recommended; Stripe fallback only |

**Preferred:** WebAuthn or TOTP. SMS should be avoided where alternatives exist.

---

## 4. Implementation Timeline

| System | Current Status | Target | Deadline |
|--------|---------------|--------|----------|
| GitHub | Org MFA enforced | Complete | Done |
| Cloudflare | MFA available | Enforce org-wide | Q2 2026 |
| SSH | Key-only auth | Add TOTP second factor | Q2 2026 |
| Grafana | Password + Tailscale | Add Cloudflare Access or OIDC | Q3 2026 |
| Stripe | MFA available | Enforce team-wide | Q2 2026 |

---

## 5. Recovery Procedures

- **Lost TOTP device:** Use backup codes (stored securely offline)
- **Lost SSH key:** Provision new key via out-of-band channel (e.g., console access)
- **Lost hardware key:** Use backup TOTP, then provision replacement hardware key
- **All factors lost:** Identity verification by CTO, followed by full credential reset

---

## 6. Audit

- Quarterly review: Verify MFA is enabled for all users across all systems
- New user onboarding: MFA setup required before production access is granted
- Access revocation: Disable all factors immediately upon offboarding
