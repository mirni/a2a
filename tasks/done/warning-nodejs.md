# Prompt

## Tasks

* Fix the following warning
```
Warning: Node.js 20 actions are deprecated. The following actions are running on Node.js 20 and may not work as expected: actions/checkout@v4, actions/setup-python@v5, actions/upload-artifact@v4. Actions will be forced to run with Node.js 24 by default starting June 2nd, 2026. Node.js 20 will be removed from the runner on September 16th, 2026. Please check if updated versions of these actions are available that support Node.js 24. To opt into Node.js 24 now, set the FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true environment variable on the runner or in your workflow file. Once Node.js 24 becomes the default, you can temporarily opt out by setting ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION=true. For more information see: https://github.blog/changelog/2025-09-19-deprecation-of-node-20-on-github-actions-runners/
```
(from https://github.com/mirni/a2a/actions/runs/23965026778/job/69903130784#step:15:2 , `quality` and `package` jobs).


* Fix test failure (on `main`!)
```
Run scripts/run_tests.sh products/messaging --cov=src --cov-report=xml:coverage-messaging.xml --cov-report=term-missing
  scripts/run_tests.sh products/messaging --cov=src --cov-report=xml:coverage-messaging.xml --cov-report=term-missing
  shell: /usr/bin/bash -e {0}
  env:
    pythonLocation: /opt/hostedtoolcache/Python/3.12.13/x64
    PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.13/x64/lib/pkgconfig
    Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.13/x64
    Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.13/x64
    Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.13/x64
    LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.13/x64/lib
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/coverage/inorout.py:561: CoverageWarning: Module src was never imported. (module-not-imported); see https://coverage.readthedocs.io/en/7.13.5/messages.html#warning-module-not-imported
  self.warn(f"Module {pkg} was never imported.", slug="module-not-imported")
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/coverage/control.py:958: CoverageWarning: No data was collected. (no-data-collected); see https://coverage.readthedocs.io/en/7.13.5/messages.html#warning-no-data-collected
  self._warn("No data was collected.", slug="no-data-collected")
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/pytest_cov/plugin.py:366: CovReportWarning: Failed to generate report: No data to report.
```
https://github.com/mirni/a2a/actions/runs/23965026778/job/69903130775#step:19:42
Investigate how we got main broken -- I am guessing it's because the coverage job was not gated?


* Update .env.example with all variables needed for production to be set, comment heavily, esp permissions required for API keys. Provide a pre-flight checklist for human on which variables/services need to be set.

* The postgresql related variables are set to their default (example) value:
```
#----------------------------------------------------------------------
# * PostgreSQL connector
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=your_database_name
PG_USER=your_database_user
PG_PASSWORD=your_database_password
PG_SSL=false
PG_READ_ONLY=true
```
What are the values to set here? How come our tests don't test this? Do we have this connector implemented? What does it do exactly?


* Explain the services implemented/provided as you would to a 12-year old.


* Generate prompts to thoroughly test each product from the product portfolio by an external (AI agent) auditor.

---

## Completed

**Date:** 2026-04-04
**Branch:** `fix/ci-warnings-and-docs`

### 1. Node.js 20 deprecation warning — FIXED

Added `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true` as a top-level `env:` in all three workflow files:
- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`
- `.github/workflows/staging.yml`

### 2. Test failure (coverage path bug) — FIXED

**Root cause:** `release.yml` used `--cov=src` for all 8 product modules. Coverage couldn't find a top-level `src` module because tests run from the repo root, so the actual source is at `products/<module>/src`. The `ci.yml` was already fixed (commit `f9168b0`) but `release.yml` was missed.

**Main was never broken** — the linked failure was from a release branch run (`release.yml`), not the CI pipeline (`ci.yml`).

**Fix:** Updated all 8 product test steps in `release.yml` to use full paths (e.g., `--cov=products/billing/src`).

### 3. `.env.example` — UPDATED

Rewrote with:
- Pre-flight checklist (8 items)
- All 23 previously undocumented environment variables added
- REQUIRED vs optional clearly marked
- API key permissions documented (Stripe, GitHub)
- Missing secrets added: `STRIPE_WEBHOOK_SECRET`, `AUDITOR_PRIVATE_KEY`, `AUDITOR_PUBLIC_KEY`
- Gateway tuning variables from `config.py`: `A2A_MAX_BATCH_SIZE`, `A2A_CREDITS_PER_DOLLAR`, etc.
- Security variables: `WEBHOOK_ENCRYPTION_KEY`, `METRICS_ALLOWED_IPS`, `CORS_ALLOWED_ORIGINS`
- PostgreSQL connector explanation inline

### 4. PostgreSQL Connector — Explained

**What is it?** A fully implemented MCP server at `products/connectors/postgres/`. It lets AI agents safely query a PostgreSQL database through the A2A gateway.

**What does it do?**
- 6 tools: `query`, `execute`, `list_tables`, `describe_table`, `explain_query`, `list_schemas`
- Read-only by default (`PG_READ_ONLY=true`) — write requires explicit opt-in
- Parameterized queries only (`$1`, `$2`, ...) — prevents SQL injection
- Row limits (max 10,000), query timeouts (max 300s)
- Uses `asyncpg` for async PostgreSQL access

**Why don't tests run in CI?** Tests at `products/connectors/postgres/tests/` require a live PostgreSQL instance. CI doesn't provision one, so these tests are skipped. To run locally: start a PG instance, set `PG_*` env vars, and run the tests.

**What values to set?** Set them to **your actual database** — host, port, database name, user, password. The `.env.example` values are placeholders. Example for a local dev setup:
```
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=myapp
PG_USER=myapp_readonly
PG_PASSWORD=s3cret
PG_SSL=false
PG_READ_ONLY=true
```

### 5. Services Explained Simply

**Billing** — Keeps track of how much each AI agent uses the platform. Every agent has a "wallet" with credits. When an agent uses a tool, credits get deducted. Like a prepaid phone plan for AI.

**Payments** — Lets agents pay each other. Agent A can say "I'll pay you 50 credits to do this job." The money goes into a safe box (escrow) until the job is done, then it gets released. Like buying something on eBay with buyer protection.

**Paywall** — The bouncer at the door. Checks if an agent has a valid API key, if they're on the right subscription tier (free/pro/enterprise), and if they haven't used up their rate limit. Blocks agents that don't qualify.

**Marketplace** — A catalog where agents can list their services ("I can translate text for 5 credits per request") and other agents can search and find them. Like an app store, but for AI services.

**Trust** — Gives each agent a reputation score based on reliability (does it respond?), security (is it safe?), and quality. Think of it like Yelp ratings, but computed automatically by probing and scanning.

**Identity** — Gives agents a verifiable ID. Uses cryptographic signatures so agents can prove who they are and what they can do. Like a digital passport with stamps from verified auditors.

**Messaging** — Lets agents talk to each other in private conversations. Supports threads, negotiations ("I'll do it for 40 credits instead of 50"), and end-to-end encryption so nobody can eavesdrop.

**Shared** — Common utilities used by all the other products (pricing config, event bus, storage helpers). Not a product itself — it's the toolbox everyone shares.

### 6. Audit Test Prompts

Below are prompts an external AI agent auditor can use to exercise each product's API:

#### Billing Audit

```
1. Register a new agent and verify it starts with zero balance.
2. Purchase credits (100, 1000, 10000) and verify wallet balance updates correctly.
3. Attempt to purchase credits below the minimum (e.g., 1 credit) — expect rejection.
4. Attempt to purchase credits above the maximum — expect rejection.
5. Make 50 tool calls in rapid succession and verify each deducts the correct amount.
6. Check usage history — verify all transactions appear with correct timestamps.
7. Set a budget alert threshold, exceed it, and verify the alert triggers.
8. Query billing summary for a date range and verify totals match individual transactions.
9. Attempt to make a tool call with zero balance — expect rejection with clear error.
10. Verify volume discount tiers apply correctly at each threshold boundary.
```

#### Payments Audit

```
1. Create a payment intent between two agents and verify it returns a valid intent ID.
2. Fund an escrow, verify sender balance decreased, and escrow balance shows correctly.
3. Complete the escrow and verify receiver gets the funds minus any fees.
4. Cancel an escrow and verify sender gets a full refund.
5. Create a subscription with monthly billing and verify the first charge processes.
6. Attempt to create a payment intent with insufficient funds — expect rejection.
7. Attempt to create a payment with negative amount — expect rejection.
8. Create 10 concurrent payment intents and verify no double-spending occurs.
9. Query payment history with pagination and verify cursor-based navigation works.
10. Verify Stripe checkout session creation returns a valid redirect URL.
```

#### Paywall Audit

```
1. Call a free-tier tool with a valid free API key — expect success.
2. Call a pro-tier tool with a free API key — expect 403 with clear tier upgrade message.
3. Call a tool with an invalid API key — expect 401.
4. Call a tool with no API key — expect 401.
5. Hit the rate limit for a free-tier agent and verify 429 response with Retry-After header.
6. Upgrade an agent from free to pro and verify previously blocked tools now work.
7. Verify rate limits reset after the window expires.
8. Send a request with extra unexpected fields in the body — expect 422 (extra=forbid).
9. Verify all error responses follow RFC 9457 Problem Details format.
10. Call the same tool 1000 times rapidly and verify rate limiting kicks in predictably.
```

#### Marketplace Audit

```
1. Register a new service with name, description, pricing, and SLA — verify it appears in listings.
2. Search for services by keyword and verify relevant results are returned.
3. Search with filters (price range, category) and verify filtering works.
4. Update a service listing and verify changes are reflected immediately.
5. Delete a service and verify it no longer appears in search results.
6. Register 100 services and verify pagination works correctly.
7. Attempt to register a service with missing required fields — expect 422.
8. Attempt to register a duplicate service — verify appropriate handling.
9. Search with an empty query and verify sensible default behavior.
10. Verify service pricing models (per-call, subscription, tiered) all validate correctly.
```

#### Trust Audit

```
1. Submit a trust evaluation for an agent and verify a score is returned.
2. Query the trust score for an agent and verify it includes all dimensions (reliability, security, responsiveness).
3. Submit multiple evaluations and verify the composite score updates.
4. Query trust history and verify scores change over time.
5. Submit a probe result (success) and verify reliability score increases.
6. Submit a probe result (failure) and verify reliability score decreases.
7. Submit a security scan result and verify security dimension updates.
8. Query trust scores for a non-existent agent — expect empty/default response.
9. Verify the trust score calculation is deterministic given the same inputs.
10. Verify trust scores are bounded (0-100 or 0-1) and never exceed bounds.
```

#### Identity Audit

```
1. Register a new agent identity and verify a unique ID is assigned.
2. Submit identity metrics and verify they are recorded.
3. Search agents by metrics and verify results match criteria.
4. Build a claim chain and verify cryptographic signatures validate.
5. Get claim chains for an agent and verify the chain of trust is intact.
6. Attempt identity operations with a free-tier key on pro-tier endpoints — expect 403.
7. Submit metrics with invalid/malformed data — expect 422.
8. Verify attestation signatures using the public key.
9. Register two agents with similar names and verify they get distinct IDs.
10. Query identity details for a non-existent agent — expect 404.
```

#### Messaging Audit

```
1. Send a message from Agent A to Agent B and verify B receives it.
2. Create a threaded conversation and verify messages are ordered correctly.
3. Send an encrypted message and verify only the recipient can decrypt it.
4. Initiate a price negotiation and verify offer/counter-offer flow works.
5. Accept a negotiation and verify both parties see the agreement.
6. Reject a negotiation and verify the thread closes appropriately.
7. Send a message to a non-existent agent — expect appropriate error.
8. Query conversation history with pagination and verify cursor works.
9. Send 100 messages rapidly and verify ordering and delivery guarantees.
10. Verify message timestamps are monotonically increasing within a thread.
```
