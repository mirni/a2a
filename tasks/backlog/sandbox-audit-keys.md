# Provision sandbox audit API keys — human operator runbook

**Priority:** P1 (blocks `sandbox-parity` CI gate going required).
**Estimated time:** 10 minutes.
**Prerequisites:** SSH access to the sandbox host, GitHub repo admin rights.

## Why this is needed

The v1.2.4 audit P1 branch (`fix/v1.2.4-audit-p1`) ships a new CI job
`sandbox-parity` in `.github/workflows/ci.yml` that runs
`tests/sandbox/` against the **live** `sandbox.greenhelix.net`
stack — Cloudflare + nginx + gunicorn + gateway + SQLite.

Unlike the in-process FastAPI TestClient suite, this job catches the
class of bug where the unit tests pass but the real stack leaks. The
external audit has repeatedly found P0s on the live sandbox that our
internal suite never hit, so we need a permanent gate that probes
the exact same path the auditors do.

The job currently runs as **`continue-on-error: true`** and
skips if the required secrets are absent. Once you complete the
steps below, a follow-up PR will flip it to required.

## What you need to do

### Step 1 — SSH into the sandbox host

```bash
ssh <your-handle>@sandbox.greenhelix.net
# or via Tailscale if direct SSH is disabled
tailscale ssh sandbox
```

The gateway's data dir lives at `/opt/a2a/data` (the default
`A2A_DATA_DIR` on production packaging). Confirm:

```bash
sudo ls -la /opt/a2a/data/ | head
# Expected: paywall.db, billing.db, payments.db, marketplace.db, ...
```

### Step 2 — Run the audit-key generator

The existing helper script creates three wallets and keys at once,
with a long expiry so CI doesn't have to rotate them weekly. Run:

```bash
# From any directory on the sandbox — the script auto-picks up
# A2A_INSTALL_DIR=/opt/a2a.
sudo -u a2a A2A_DATA_DIR=/opt/a2a/data \
    /opt/a2a/venv/bin/python /opt/a2a/scripts/generate_audit_keys.py \
    --data-dir /opt/a2a/data \
    --output /tmp/audit-keys-ci.env \
    --expires 8760   # 1 year — CI secrets, not human-handled keys
```

Expected output on stderr:

```
Keys written to /tmp/audit-keys-ci.env
  free          a2a_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  pro           a2a_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
  enterprise    a2a_zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz
```

The three agents created:

| agent_id | tier | balance | scopes |
|----------|------|---------|--------|
| `audit-free` | free | 10,000 credits | read, write |
| `audit-pro` | pro | 100,000 credits | read, write |
| `audit-admin` | enterprise | 999,999 credits | read, write, **admin** |

### Step 3 — Capture the three keys

```bash
sudo cat /tmp/audit-keys-ci.env
```

Three lines matter:

```
FREE_API_KEY=a2a_xxxxxxxxxxxx...
PRO_API_KEY=a2a_yyyyyyyyyyyy...
ENTERPRISE_API_KEY=a2a_zzzzzzzzzzzz...
```

**Copy these three values to a secure note.** You'll paste them
into GitHub in Step 4.

After copying, **shred the file** — never leave plaintext keys on
disk:

```bash
sudo shred -u /tmp/audit-keys-ci.env
```

### Step 4 — Sanity-check each key against the sandbox

From your local machine:

```bash
curl -H "Authorization: Bearer <FREE_API_KEY>" \
     https://sandbox.greenhelix.net/v1/health
# Expected: {"status":"ok","version":"1.2.5",...}  HTTP 200

curl -H "Authorization: Bearer <FREE_API_KEY>" \
     https://sandbox.greenhelix.net/v1/infra/keys
# Expected: HTTP 403 (free tier must NOT see infra)

curl -H "Authorization: Bearer <PRO_API_KEY>" \
     https://sandbox.greenhelix.net/v1/infra/keys
# Expected: HTTP 403 (pro tier must NOT see infra either)

curl -H "Authorization: Bearer <ENTERPRISE_API_KEY>" \
     https://sandbox.greenhelix.net/v1/infra/keys
# Expected: HTTP 200 with a list of keys (admin scope → 200)
```

All four behaviours must match before you wire the secrets into CI.
If the **admin** key returns 403, the enterprise tier needs the
`admin` scope — re-run Step 2 or use `scripts/admin_cli.py` to add
the scope manually (`add_scope` command).

### Step 5 — Add the secrets to GitHub Actions

Go to:
`https://github.com/mirni/a2a/settings/secrets/actions`

Click **"New repository secret"** three times and create:

| Secret name | Value |
|-------------|-------|
| `SANDBOX_AUDIT_FREE_KEY` | `a2a_xxxxxxxx...` (the FREE_API_KEY) |
| `SANDBOX_AUDIT_PRO_KEY` | `a2a_yyyyyyyy...` (the PRO_API_KEY) |
| `SANDBOX_AUDIT_ADMIN_KEY` | `a2a_zzzzzzzz...` (the ENTERPRISE_API_KEY — **despite the name** this holds the admin-scoped key) |

**Important:** the CI variable is named `SANDBOX_AUDIT_ADMIN_KEY`
but the underlying agent tier is `enterprise` with the `admin`
scope. The naming mismatch is deliberate — the test code thinks
of tiers as "free / pro / admin" because that's how the audit
framework talks about them.

### Step 6 — Trigger a CI run on any open PR

Push an empty commit or re-run CI on any open PR:

```bash
git commit --allow-empty -m "ci: verify sandbox-parity gate"
git push
```

Watch the **`sandbox-parity`** job:

```bash
gh run list --limit 3
gh run view <run-id> --log | grep -A 5 sandbox-parity
```

**Expected on success:** 10 tests pass in `tests/sandbox/` —
multi-tenant probe, /v1/execute 410, idempotency collision, and
health SLO < 1000ms.

**If some tests fail:** that's the whole point of the gate. The
failure message tells you exactly which class of regression
leaked (admin tier, 410, idempotency, latency). Fix the finding
and re-run.

### Step 7 — Make the gate required

Once the job is green, open a follow-up PR that changes
`.github/workflows/ci.yml`:

```yaml
sandbox-parity:
  needs: [quality]
  if: github.event_name == 'pull_request' && github.base_ref == 'main'
  runs-on: ubuntu-latest
-  continue-on-error: true  # Non-blocking until sandbox keys are provisioned
+  # Required gate: audit-probe parity against the live sandbox.
  steps:
    ...
```

And in
`https://github.com/mirni/a2a/settings/branches` → `main` →
**Require status checks to pass** — add `sandbox-parity` to the
list of required checks.

### Step 8 — Schedule a yearly key rotation reminder

The keys generated in Step 2 expire in 1 year (`--expires 8760`).
Add a calendar reminder **11 months out** to re-run this runbook
and update the three GitHub secrets.

---

## Troubleshooting

### `generate_audit_keys.py` crashes with `ImportError: gateway.src.bootstrap`

The sandbox is running an older package version that doesn't have
the bootstrap module. Re-run after the next deploy, or fall back
to the manual path below.

### Manual key creation (fallback)

If the generator is unavailable:

```bash
# For each of free / pro / enterprise:
sudo -u a2a /opt/a2a/venv/bin/python -c "
import asyncio, os
os.environ['A2A_DATA_DIR'] = '/opt/a2a/data'
import gateway.src.bootstrap  # noqa
from billing_src.tracker import UsageTracker
from paywall_src.keys import KeyManager
from paywall_src.storage import PaywallStorage

async def main():
    ps = PaywallStorage('sqlite:///opt/a2a/data/paywall.db')
    await ps.connect()
    tr = UsageTracker('sqlite:///opt/a2a/data/billing.db')
    await tr.connect()
    # Change these per-tier:
    agent_id = 'audit-admin'
    tier = 'enterprise'
    scopes = ['read', 'write', 'admin']
    balance = 999999.0
    try:
        await tr.wallet.create(agent_id, initial_balance=balance, signup_bonus=False)
    except ValueError:
        pass
    info = await KeyManager(ps).create_key(agent_id, tier=tier, scopes=scopes)
    print(f'{tier}: {info[\"key\"]}')
    await ps.close(); await tr.close()

asyncio.run(main())
"
```

### `curl` returns 502 / 520 / timeout

The sandbox backend is down. Check `systemctl status a2a-gateway-test`
on the host and `journalctl -u a2a-gateway-test -n 100`.

### CI reports "sandbox audit keys not configured"

The secret names in Step 5 must match **exactly**: case-sensitive,
no trailing newline. Re-check in GitHub and re-save if unsure.

---

## Owner

Human ops (the person who manages sandbox credentials). This task
cannot be automated by Claude — all three secrets need to cross an
org boundary (sandbox → GitHub).

## Completion criteria

- [ ] Three keys generated and sanity-checked (Step 4).
- [ ] Three GitHub secrets set (Step 5).
- [ ] Next CI run shows `sandbox-parity` job passing 10 tests.
- [ ] Follow-up PR flips `continue-on-error` to `false` and marks
      the check as required.
- [ ] Yearly rotation reminder set on your calendar.
