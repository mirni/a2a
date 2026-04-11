# Create sandbox audit API keys (human task)

## Context

The v1.2.4 audit P0 remediation PR (`fix/v1.2.4-audit-p0`) adds a
`tests/sandbox/` suite that exercises the production sandbox with
real API keys at free / pro / admin tiers. The sandbox-parity CI
job is deferred to a follow-up release because it needs secrets
that only a human can provision.

## Action

1. In the production sandbox dashboard (or via `scripts/admin_cli.py`),
   create three API keys under dedicated audit agents:
   - `audit-free` — free tier, all default scopes
   - `audit-pro` — pro tier, all default scopes
   - `audit-admin` — pro tier + `admin` scope
2. In the GitHub repo settings → Secrets and variables → Actions,
   add the three secrets:
   - `SANDBOX_AUDIT_FREE_KEY`
   - `SANDBOX_AUDIT_PRO_KEY`
   - `SANDBOX_AUDIT_ADMIN_KEY`
3. Announce readiness in the follow-up PR so the sandbox-parity
   job can be wired into `.github/workflows/ci.yml`.

## Follow-up

Tracked by `tasks/backlog/v1.2.4-audit-p1.md`.
