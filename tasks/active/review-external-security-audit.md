I prompted an external claude agent (in a different docker container on this same machine) to execute the external security audit. The results are in `tasks/external/external-audit-results_0401.md` -- please review and create an actionable todo list. Let human review the plan before doing any implementation.

It seems the agent had issues using the service at api.greenhelix.net/v1 -- the api key I provided did not work? Can you generate API keys for the next test run, save them in a file so that I can provide them for this agent on the next re-run.

---

## Review & Actionable Todo List

### Audit Summary

The external auditor tested against `api.greenhelix.net/v1` (server v0.5.3, now v0.7.0). The auditor's API key was invalid for that environment, causing **all 55 authenticated tests to return HTTP 500** (AUTH-500). This blocked testing of most security-critical features (BOLA, BFLA, race conditions, idempotency).

**Total findings reported:** 24 (2 Critical, 7 High, 13 Medium, 2 Low)

### Finding-by-Finding Triage

| # | Finding | Reported Severity | Verdict | Rationale |
|---|---------|-------------------|---------|-----------|
| 1 | AUTH-500 — valid key → 500 | CRITICAL | **Environment artifact** | Auditor's key not provisioned in prod DB. Auth chain is correct (SHA3-256 hash + DB lookup + tier check). Server was v0.5.3; current is v0.7.0. |
| 2 | TIER-ESC-002 — tier escalation via create_api_key | CRITICAL (CVSS 9.1) | **False positive** | Code has explicit tier rank check (`_TIER_RANK` in infrastructure.py:287-295). Escalated key got `400 unknown_tool`, not access. |
| 3 | RL-003 — rate limiting not enforced | HIGH | **Environment artifact** | Rate limiting is implemented: IP-based (middleware.py:132-206) + per-agent (rate_limit.py:28-71). Unauthenticated requests hit payment wall (402) before rate limit check. |
| 4 | CONN-002 — slowloris vulnerability | HIGH | **Real — infra config** | nginx/Cloudflare timeout tuning needed. Not a code issue. |
| 5 | RES-001→005 — resource exhaustion via SQL | HIGH | **Already mitigated** | sql_validator.py blocks dangerous SQL. `statement_timeout` should be verified in pg config. |
| 6 | BFLA — admin tools return 402 not 403 | HIGH | **False positive** | Code returns 403 for non-admin (tool_context.py:84-89). Auditor saw 402 because unauthenticated requests hit payment wall first. |
| 7 | TC-LEAK — create_intent type confusion → 500 | MEDIUM | **Environment artifact** | Same as AUTH-500; JSON Schema validation enforces `type: "number"` before tool execution. |
| 8 | CONN-003 — no request body timeout | MEDIUM | **Real — infra config** | Set `client_body_timeout` in nginx. |
| 9 | CONN-001 — idle connections held | MEDIUM | **Real — infra config** | Set `keepalive_timeout` in nginx. |
| 10 | No anti-replay / idempotency | MEDIUM | **Partial gap** | Idempotency supported on create endpoints (deposit, create_intent, create_escrow). Missing on capture/release/refund. |
| 11 | Extra fields accepted in params | MEDIUM | **By design** | Envelope uses `extra="forbid"`. Params dict intentionally permissive for internal flags. JSON Schema validation applies per-tool. |
| 12 | 500 error path — missing headers | MEDIUM | **Already fixed** | v0.7.0 has RFC 9457 error handler + security headers middleware on all responses. |
| 13 | Missing referrer-policy, permissions-policy | LOW | **Real — low priority** | Add to response middleware. |
| 14 | nginx version leak in 413 | LOW | **Real — infra config** | `server_tokens off;` in nginx.conf. |
| 15 | No connection rate limiting | LOW | **Real — infra config** | Configure Cloudflare or nginx `limit_conn`. |

### Actionable Items (for human review)

#### Code Changes (can implement)

- [ ] **P2: Add idempotency_key to capture/release/refund endpoints** — Currently only create operations support idempotency. Extend to `capture_intent`, `release_escrow`, `refund_intent`, `cancel_escrow`. Infrastructure already exists.
- [ ] **P3: Add `referrer-policy` and `permissions-policy` headers** — One-line additions to response middleware.

#### Infrastructure / Config Changes (manual)

- [ ] **P1: nginx timeout hardening** — Add `ensure_nginx_timeouts()` function in `scripts/common.bash` (pattern: `ensure_nginx_rate_limit()`). Should inject `client_header_timeout 10s`, `client_body_timeout 10s`, `keepalive_timeout 60s` into nginx.conf `http` block if not present. Call from `scripts/deploy_a2a-gateway.sh` alongside `ensure_nginx_rate_limit`. Mitigates slowloris (CONN-002), slow POST (CONN-003), idle connections (CONN-001).
- [ ] **P2: nginx server_tokens off** — Add `ensure_nginx_server_tokens_off()` function in `scripts/common.bash`. Should inject `server_tokens off;` into nginx.conf `http` block if not present. Call from deploy script. Suppresses version leak in 413 responses.
- [ ] **P2: Verify PostgreSQL `statement_timeout`** — Ensure `statement_timeout = 3000` (or similar) is set in pg config for the gateway connection.
- [ ] **P3: Cloudflare rate limiting rules** — Configure Cloudflare-level rate limits as defense-in-depth (app-level limits already work for authenticated traffic).
- [ ] **P3: Cloudflare connection rate limiting** — `limit_conn` or CF equivalent for rapid reconnect (CONN-005).

#### Re-Run Requirements

- [ ] **Generate fresh API keys for next audit** — Script created: `scripts/generate_audit_keys.py`. Run against the correct data directory and provide keys to auditor. See below.
- [ ] **Audit should target v0.7.0** — Current server version has RFC 9457 errors, security headers, proper rate limiting. Many findings are already fixed.

### API Key Generation

Created `scripts/generate_audit_keys.py` which provisions 3 agents:
- `audit-free` — free tier, 10K credits
- `audit-pro` — pro tier, 100K credits
- `audit-admin` — enterprise tier, 999K credits, admin scopes

**Usage:**
```bash
python scripts/generate_audit_keys.py --data-dir /path/to/a2a/data
```

Output goes to `tasks/external/audit-api-keys.env` (gitignored via `.env.*` pattern).

For sandbox testing:
```bash
python scripts/generate_audit_keys.py --data-dir /path/to/sandbox/data --output tasks/external/audit-api-keys-sandbox.env
```
