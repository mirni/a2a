# Black-Box SDK & API Audit — A2A Commerce Platform

You are a QA/security agent. Your mission: test all three distribution channels
of the A2A Commerce Platform (Python SDK, TypeScript SDK, Docker container)
by creating **3 independent agents**, each working in a clean directory, against
the live sandbox at `https://sandbox.greenhelix.net`.

Each agent must go through the FULL lifecycle: install → discover → register →
transact → verify. Report on security, usability, correctness, and documentation.

---

## GLOBAL RULES

- Each agent works in its OWN clean directory (`/tmp/audit-pypi/`, `/tmp/audit-npm/`, `/tmp/audit-docker/`)
- Each agent registers with a UNIQUE agent ID: `audit-pypi-<timestamp>`, `audit-npm-<timestamp>`, `audit-docker-<timestamp>`
- Target API: `https://sandbox.greenhelix.net`
- NO source code access. Treat this as a black-box test. Only use public docs.
- Log every HTTP request/response status, latency, and headers observed.
- All currency values must be Decimal/string, never float.

---

## AGENT 1: Python SDK (PyPI)

### Setup
```bash
mkdir -p /tmp/audit-pypi && cd /tmp/audit-pypi
python3 -m venv venv && source venv/bin/activate
pip install a2a-greenhelix-sdk
```

### Tests to Execute

#### T1.1 — Discovery & Documentation
- [ ] Fetch `GET /v1/health` — verify `status`, `version`, `tools` fields
- [ ] Fetch `GET /.well-known/agent.json` — verify A2A agent card has `name`, `skills`, `authentication`, `capabilities`
- [ ] Fetch `GET /v1/onboarding` — verify it returns enriched OpenAPI with `x-onboarding`
- [ ] Fetch `GET /v1/pricing` — count tools returned, verify each has `name`, `service`, `pricing`, `tier_required`
- [ ] Fetch `GET /v1/pricing/tiers` — verify tier names: free, starter, pro, enterprise

#### T1.2 — Registration & Onboarding
- [ ] Call `POST /v1/register` with `{"agent_id": "<your-id>"}` — expect 201, verify response has `api_key`, `balance`, `tier`
- [ ] Call `POST /v1/register` again with SAME agent_id — expect 409 Conflict
- [ ] Use the returned API key for all subsequent calls
- [ ] Verify signup bonus: call `client.get_balance(agent_id)` — expect 500.0 credits

#### T1.3 — SDK Usability Audit
- [ ] Instantiate `A2AClient(base_url=..., api_key=...)` — does it work without context manager?
- [ ] Instantiate `async with A2AClient(...) as client:` — verify cleanup on exit
- [ ] Call `client.health()` — verify return type is a proper response object (not raw dict)
- [ ] Call a method with wrong params — verify it raises a clear, typed exception (not generic)
- [ ] Trigger rate limit (if feasible) — verify `RateLimitError` is raised with `retry_after`
- [ ] Call `client.execute("nonexistent_tool", {})` — verify `ToolNotFoundError`
- [ ] Verify all public exports match what's documented: `A2AClient`, `A2AError`, `AuthenticationError`, `InsufficientBalanceError`, `RateLimitError`, `ToolNotFoundError`

#### T1.4 — Billing & Payments Flow
- [ ] `client.get_balance(agent_id)` — record initial balance
- [ ] `client.deposit(agent_id, "100.00")` — verify balance increases by 100
- [ ] `client.create_payment_intent(payer=agent_id, payee=agent_id, amount="10.00", currency="CREDITS", description="self-test")` — verify intent created
- [ ] Capture the intent — verify settlement
- [ ] `client.get_balance(agent_id)` — verify balance reflects charges
- [ ] Attempt `client.deposit(agent_id, "-50.00")` — expect rejection (negative amount)
- [ ] Attempt `client.deposit(agent_id, "99999999.99")` — check if deposit limits enforced

#### T1.5 — Identity & Trust
- [ ] `client.get_agent_identity(agent_id)` — verify identity was auto-registered at signup
- [ ] `client.get_agent_reputation(agent_id)` — verify reputation object returned
- [ ] `client.verify_agent(agent_id, message="hello", signature="invalid")` — expect verification failure

#### T1.6 — Marketplace
- [ ] `client.search_services(query="billing")` — verify returns list
- [ ] `client.register_service(...)` — note if tier restriction applies (may need pro tier)

#### T1.7 — Security Checks
- [ ] Send request with no API key — expect 401/403
- [ ] Send request with malformed key `"not_a_real_key"` — expect 401
- [ ] Send request with extra fields in body (`{"agent_id": "x", "evil": "payload"}`) — expect 422 (extra=forbid)
- [ ] Check response headers for: `X-Content-Type-Options`, `Strict-Transport-Security`, `Content-Security-Policy`, `X-Request-Id`
- [ ] Send agent_id with 200+ chars — expect rejection (AgentIdLength middleware)
- [ ] Check error responses are RFC 9457 format: `type`, `title`, `status`, `detail`
- [ ] Try accessing another agent's wallet: `client.get_balance("someone-elses-agent")` — expect 403 (ownership check)
- [ ] Verify all responses use `application/json` content type
- [ ] Check that no response leaks internal paths, stack traces, or secrets

---

## AGENT 2: TypeScript SDK (npm)

### Setup
```bash
mkdir -p /tmp/audit-npm && cd /tmp/audit-npm
npm init -y
npm install @greenhelix/sdk
```

### Tests to Execute

#### T2.1 — SDK Installation Audit
- [ ] Verify zero runtime dependencies (only devDeps)
- [ ] Verify TypeScript types are included (`dist/index.d.ts` exists in node_modules)
- [ ] Verify package exports: `A2AClient`, `A2AError`, `AuthenticationError`, etc.
- [ ] Check `package.json` metadata: description, repository, license, keywords

#### T2.2 — Registration & Lifecycle
- [ ] Create `test.mjs`:
```javascript
import { A2AClient, A2AError } from '@greenhelix/sdk';

const client = new A2AClient({
  baseUrl: 'https://sandbox.greenhelix.net',
  apiKey: '' // will register first
});

// Step 1: Register via raw fetch (no SDK method for register)
const regResp = await fetch('https://sandbox.greenhelix.net/v1/register', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ agent_id: `audit-npm-${Date.now()}` })
});
const regData = await regResp.json();
console.log('Registration:', regResp.status, regData);

// Step 2: Use the API key
const authedClient = new A2AClient({
  baseUrl: 'https://sandbox.greenhelix.net',
  apiKey: regData.api_key
});

// Step 3: Health check
const health = await authedClient.health();
console.log('Health:', health);

// Continue with all tests...
```
- [ ] Run: `node test.mjs`

#### T2.3 — Parity with Python SDK
- [ ] Verify same methods exist: `health()`, `getBalance()`, `deposit()`, `createPaymentIntent()`, `capturePayment()`, `registerAgent()`, `searchServices()`, `sendMessage()`
- [ ] Call each core method and verify response structure matches Python SDK
- [ ] Verify error types match: `A2AError`, `AuthenticationError`, `InsufficientBalanceError`, `RateLimitError`

#### T2.4 — Error Handling
- [ ] Call with invalid API key — verify `AuthenticationError` thrown (not generic Error)
- [ ] Call nonexistent tool — verify `ToolNotFoundError`
- [ ] Verify errors have `.code`, `.status`, `.message` properties

#### T2.5 — Security (same checks as T1.7 but via fetch)
- [ ] Extra fields rejection (extra=forbid)
- [ ] Security headers present
- [ ] RFC 9457 error format
- [ ] No information leakage in errors
- [ ] Ownership isolation between agents

---

## AGENT 3: Docker Container

### Setup
```bash
mkdir -p /tmp/audit-docker && cd /tmp/audit-docker
```

### Tests to Execute

#### T3.1 — Image Pull & Run
- [ ] `docker pull ghcr.io/mirni/a2a-gateway:latest` (or build from public Dockerfile)
- [ ] If no public image, build from Dockerfile:
  ```bash
  git clone https://github.com/mirni/a2a.git && cd a2a
  docker build -t a2a-gateway .
  ```
- [ ] `docker run -d --name a2a-test -p 9000:8000 a2a-gateway`
- [ ] Wait for healthcheck: `curl -f http://localhost:9000/v1/health` (retry up to 30s)

#### T3.2 — Container Security Audit
- [ ] Verify runs as non-root: `docker exec a2a-test whoami` — expect `a2a`
- [ ] Verify no secrets in image layers: `docker history a2a-gateway` — check for leaked env vars
- [ ] Verify no unnecessary packages: `docker exec a2a-test dpkg -l | wc -l`
- [ ] Check exposed ports: only 8000
- [ ] Verify healthcheck is configured: `docker inspect a2a-test --format='{{json .Config.Healthcheck}}'`
- [ ] Verify data directory permissions: `docker exec a2a-test ls -la /var/lib/a2a`

#### T3.3 — API Functional Tests (against local container)
- [ ] `GET /v1/health` — verify 200
- [ ] `GET /.well-known/agent.json` — verify agent card
- [ ] `POST /v1/register {"agent_id": "audit-docker-<timestamp>"}` — verify 201
- [ ] Full billing cycle: deposit → payment intent → capture → check balance
- [ ] Full identity cycle: register agent → get identity → verify signature

#### T3.4 — Resilience Tests
- [ ] Send 50 concurrent requests to `/v1/health` — verify all return 200, measure p50/p95/p99 latency
- [ ] Send request with 2MB body — expect 413 or rejection (BodySizeLimit middleware)
- [ ] Send request with `Content-Type: text/plain` to POST endpoint — expect 422
- [ ] Stop and restart container — verify data persists in volume mount
- [ ] Send malformed JSON `{invalid` — expect 422, not 500

#### T3.5 — Volume & Persistence
- [ ] Register agent, deposit credits, stop container
- [ ] Start container with same volume
- [ ] Verify agent and balance still exist

#### T3.6 — Environment Variable Handling
- [ ] Run without any env vars — verify sane defaults (port 8000, SQLite storage)
- [ ] Run with `FORCE_HTTPS=1` — verify HTTP requests get redirected
- [ ] Run with `CORS_ALLOWED_ORIGINS=https://example.com` — verify CORS headers on preflight

---

## OUTPUT FORMAT

For each agent, produce a structured report:

```markdown
# Agent <N>: <Channel> Audit Report

## Environment
- Date: <ISO date>
- SDK Version: <version installed>
- API Target: <URL>
- Agent ID: <registered ID>

## Test Results

| Test ID | Description                    | Result | Latency | Notes |
|---------|--------------------------------|--------|---------|-------|
| T1.1.1  | Health endpoint                | PASS   | 120ms   |       |
| T1.1.2  | Agent card discovery           | PASS   | 95ms    |       |
| ...     | ...                            | ...    | ...     | ...   |

## Security Findings

| Severity | Finding                        | Evidence                  | Recommendation |
|----------|--------------------------------|---------------------------|----------------|
| HIGH     | <description>                  | <response excerpt>        | <fix>          |
| MEDIUM   | <description>                  | <header value>            | <fix>          |

## Usability Assessment

- **Installation**: <1-5 score> — <notes>
- **Documentation**: <1-5 score> — <notes>
- **Error Messages**: <1-5 score> — <notes>
- **Type Safety**: <1-5 score> — <notes>
- **SDK Completeness**: <1-5 score> — <notes>

## SDK/API Bugs Found
1. <description + reproduction steps>

## Recommendations
1. <actionable improvement>
```

## FINAL DELIVERABLE

Combine all three agent reports into a single `SDK_AUDIT_REPORT.md` with:
1. Executive summary (pass rate, critical findings, overall usability score)
2. Per-channel detailed report (Agent 1, 2, 3)
3. Cross-channel parity matrix (which features work in Python but not TS, etc.)
4. Security findings consolidated and deduplicated
5. Prioritized recommendations (P0/P1/P2)
