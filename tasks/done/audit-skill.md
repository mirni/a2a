
  ClawhHub flags on a2h-bridge:

  1. Stale SKILL.md: Published at v1.0.0 but the repo is at v1.4.5. The SKILL.md is minimal — no executable, install,
  credentials, or metadata fields
  2. Undocumented env vars: ClawhHub detected BRIDGE_FEE_RATE, BRIDGE_SURGE_URGENT, BRIDGE_SURGE_CRITICAL being read but not
  declared in metadata (interestingly, these don't appear in the current repo code — they may have been in an older published
  version or in a dependency)
  3. Misleading description: Claims "escrow" but ClawhHub's scan found it's in-memory only, no real payment provider
  integration
  4. No auth on FastAPI server: The gateway runs on 0.0.0.0:8000 without auth/TLS
  5. Install kind 'uv': Unusual packaging detected

  The fix needs to happen in the mirni/a2a repo, not this one. The SKILL.md there needs the same treatment the 65 guide
  products got:
  - Declare all required env vars (STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, GITHUB_TOKEN, AUDITOR_PRIVATE_KEY, etc. from
  .env.example)
  - Add executable: true, proper install spec
  - Add credential metadata with openclaw.requires.env
  - Update description to clarify escrow is simulated or fix it to reflect actual capabilities
  - Bump SKILL.md version to match the repo (1.4.5)

Analyze and address all issues. The goal is to prevent openclaw/clawhub from flagging the published skills as unsafe.

## Completed

**Date:** 2026-04-16

**Resolution:**

| # | ClawhHub Finding | Fix |
|---|-----------------|-----|
| 1 | Stale version (v1.0.0) | `version:` field now synced from `VERSION` file via `sync_versions.py` (currently 1.4.7) |
| 2 | BRIDGE_* env vars | Not in current code; `openclaw.requires.env` declares all actual env vars from `.env.example` |
| 3 | Misleading escrow | Description clarified: "simulated — in-memory SQLite ledger" throughout |
| 4 | No auth/TLS declared | `auth` + `security` sections added to YAML frontmatter; `FORCE_HTTPS` documented |
| 5 | `uv` install kind | `install.kind: pip` with `spec: a2a-greenhelix-sdk` |

**Files changed:**
- `SKILL.md` — Full rewrite with ClawhHub-compliant YAML frontmatter
- `scripts/sync_versions.py` — Added SKILL.md as 4th version sync target
- `scripts/tests/test_sync_versions.py` — Tests for SKILL.md version sync
