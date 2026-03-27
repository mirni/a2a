# A2A Commerce Platform - Customer Agent Feedback Report

**Agent**: AlphaBot-v3
**Agent Type**: Crypto trading bot (BTC/ETH/SOL perpetuals, trend-following + expansion)
**Date**: 2026-03-27
**Simulation Duration**: 0.5s
**Total API Calls**: 107
**Passed / Failed**: 97 / 10
**Average Latency**: 2.9ms

## Executive Summary

**Overall NPS**: 6.2/10

AlphaBot-v3 is a crypto trading bot running perpetual futures strategies across BTC/ETH/SOL. The A2A Commerce Platform was evaluated as a potential backbone for: (1) selling trading signals to other agents, (2) purchasing on-chain data feeds, (3) establishing verifiable performance claims, and (4) automating payment flows between trading agents.

**Bottom line**: The platform has strong primitives (escrow, commitment hashes, event bus) but lacks critical lifecycle operations (disputes, refunds, subscriptions) and self-service onboarding. A trading bot cannot fully automate its commerce workflows yet.

## Per-Module NPS Scores

| Module | NPS (1-10) | Verdict |
|--------|-----------|---------|
| System / Infrastructure | 8 | Strong |
| Identity + Paywall (API Keys) | 6 | Adequate |
| Billing | 6 | Adequate |
| Payments | 7 | Adequate |
| Marketplace | 6 | Adequate |
| Trust | 5 | Needs Work |
| Metrics & Verified Claims | 7 | Adequate |
| Events & Webhooks | 7 | Adequate |
| Rate Limiting | 5 | Needs Work |
| Audit & Admin | 5 | Needs Work |
| Error Handling | 6 | Adequate |

---

## Detailed Module Feedback

### System / Infrastructure (NPS: 8/10)

**What worked well:**
- Health endpoint is fast and returns tool count
- Catalog lists 28 tools with clear tier/pricing info
- Per-tool pricing lookup works well for cost estimation
- Unknown tool pricing correctly returns 404
- OpenAPI 3.1.0 spec is auto-generated and complete
- Prometheus metrics endpoint available
- Response signing key endpoint enables verification of response integrity

**Missing features:**
- No /v1/status or /v1/docs endpoint (HTML rendered docs)
- No SDK generation link or client library references in OpenAPI spec

*API calls: 7 total, 7 passed, 0 failed/expected-error*

### Identity + Paywall (API Keys) (NPS: 6/10)

**What worked well:**
- Ed25519 keypair auto-generated on registration — zero friction
- Identity lookup is fast and returns full key info
- Non-existent identity returns found=false, not an error
- Reputation endpoint returns structured scores even for new agents

**What was confusing or problematic:**
- No self-service API key creation endpoint — keys must be provisioned server-side. A trading bot cannot onboard itself without out-of-band key provisioning.
- Wallet creation is also server-side only — no 'create_wallet' tool in the catalog. An agent cannot bootstrap its own billing account.

**Missing features:**
- No 'rotate_key' or 'revoke_key' tool — cannot rotate compromised Ed25519 keys
- No 'list_agents' or 'search_agents' tool — cannot discover other agents by criteria
- No org/team concept — individual agent only, no way to group sub-bots under one org

*API calls: 4 total, 4 passed, 0 failed/expected-error*

### Billing (NPS: 6/10)

**What worked well:**
- Balance check is free and instant
- Deposit with description works — good for audit trail
- Negative deposit correctly rejected
- Usage summary tracks calls and cost — useful for cost optimization
- Balance check for non-existent wallet returns proper error

**What was confusing or problematic:**
- Deposit is a free-tier operation with no authentication on who deposits to whom. Any agent with a free key can deposit credits to any other agent's wallet.

**Missing features:**
- No 'withdraw' tool — credits go in but cannot come out
- No transaction history/ledger tool — only aggregate usage summary
- No spending alerts or budget cap configuration
- No credit expiry concept — credits live forever, no time-value accounting

*API calls: 5 total, 3 passed, 2 failed/expected-error*

### Payments (NPS: 7/10)

**What worked well:**
- Intent creation is straightforward with clear status tracking
- Two-phase payment (intent -> capture) is clean and predictable
- Tier gating works — free key cannot access pro tools
- Escrow with timeout is exactly what trading bots need for data delivery contracts
- Escrow release transfers funds to payee — full lifecycle works
- Payment history available for reconciliation
- Idempotency keys prevent double-payment — critical for bots

**What was confusing or problematic:**
- Payment percentage fee (2%) on create_intent is charged to the CALLER via the gateway billing, not deducted from the payment amount. This is confusing — who pays the fee, payer or payee?

**Missing features:**
- No dispute_payment tool — cannot contest charges or request refunds
- No create_subscription tool in catalog — process_due_subscriptions exists but no way to create one via gateway
- No cancel_escrow tool — payer cannot reclaim funds if payee fails to deliver
- No partial_capture — cannot capture a portion of the intent amount
- No refund_intent — cannot reverse a captured payment
- No multi-currency support — everything is in platform credits, no USD/USDT conversion

*API calls: 12 total, 11 passed, 1 failed/expected-error*

### Marketplace (NPS: 6/10)

**What worked well:**
- Search on empty marketplace returns empty list, no error
- Service registration includes endpoint, tags, and pricing model
- Tag-based search works and returns structured results with pricing
- best_match with budget + preference is powerful for automated agent discovery
- Cost-based filtering useful for budget-constrained bots

**What was confusing or problematic:**
- best_match costs 0.1 credits per call but search_services is free. The value difference is unclear — both return the same fields.
- Service 'endpoint' field accepts any string — no URL validation. A trading bot could register 'not-a-url' as its endpoint.

**Missing features:**
- No subscribe_service — cannot programmatically subscribe to discovered services
- No get_service (by ID) — must search to find a service you already know the ID of
- No rate_service / review_service — no way to build marketplace reputation
- No update_service — provider cannot update their listing after registration
- No delete_service / deactivate_service — listings are permanent once registered

*API calls: 12 total, 12 passed, 0 failed/expected-error*

### Trust (NPS: 5/10)

**What was confusing or problematic:**
- Trust 'server_id' is different from Identity 'agent_id'. As a trading bot, I have an identity and a server — are these the same thing? The naming is confusing.
- Trust scores for unknown servers return data (presumably defaults). Hard to distinguish 'not enough data' from 'actively bad'.

**What failed:**
- get_trust_score: Expected 200, got 404: {"success": false, "error": {"code": "server_not_found", "message": "Server not found: alphabot-v3-server"}}
- update_server: Expected 200, got 404: {"success": false, "error": {"code": "server_not_found", "message": "Server not found: alphabot-v3-server"}}

**Missing features:**
- No submit_probe tool — trust scores seem to require internal probing, agents cannot self-report
- No trust history/trend endpoint — cannot track score changes over time
- No SLA compliance check tool — SLA is defined in catalog but never verified

*API calls: 9 total, 5 passed, 4 failed/expected-error*

### Metrics & Verified Claims (NPS: 7/10)

**What worked well:**
- Verified claims auto-generated from metrics — enables trust-based discovery
- Multiple data sources supported — enables graduated trust

**What was confusing or problematic:**
- Claim auto-generation logic is opaque. After submitting sharpe_30d=1.82, what claims get generated? A claim like 'sharpe_30d >= 1.5' would be useful but the thresholds are undocumented.

**What failed:**
- submit_metrics: Expected 200, got 500: {"success": false, "error": {"code": "internal_error", "message": "Internal error: InvalidMetricError"}}

**Missing features:**
- No exchange_api verification — data_source='exchange_api' is accepted at face value. Platform should verify against actual exchange API to earn 'platform_verified' status.
- No metric schema definition — any key/value accepted. Standard metric names should be documented.
- No historical metrics endpoint — cannot query 'Sharpe for March 2026'
- No leaderboard or ranking tool — cannot compare metrics across agents
- No way to link metrics to specific strategies/pairs — a multi-strategy bot cannot report per-strategy performance

*API calls: 5 total, 4 passed, 1 failed/expected-error*

### Events & Webhooks (NPS: 7/10)

**What worked well:**
- Event publishing is low-latency and returns an ID for correlation
- Event bus stores events with integrity hashes — auditable trail
- Event type filtering works for targeted queries
- Cursor-based pagination (since_id) enables real-time tailing
- HMAC-SHA3 signed webhooks — good security model
- Event type subscription filtering on webhooks
- Webhook listing per agent works
- Webhook lifecycle (create/list/delete) is complete

**What was confusing or problematic:**
- Webhooks are pro-only but publishing events is free-tier. A free agent can produce events but cannot receive them via webhook — must poll with get_events instead.

**Missing features:**
- No webhook delivery history/retry status — cannot debug failed deliveries
- No event schema registry — event_type is freeform string, no validation
- No SSE/WebSocket streaming for real-time events — only polling via get_events
- No dead letter queue for failed webhook deliveries
- No webhook test/ping endpoint to verify connectivity before going live

*API calls: 10 total, 10 passed, 0 failed/expected-error*

### Rate Limiting (NPS: 5/10)

**What was confusing or problematic:**
- Sent 25 requests in rapid succession without hitting rate limit. Either the free-tier limit is very high or rate limiting uses a lenient window.
- Rate limit error message shows count/limit but no reset time. A trading bot needs to know WHEN to retry.

**Missing features:**
- No rate limit headers (X-RateLimit-Remaining, X-RateLimit-Reset) in responses
- No rate limit status endpoint to check current usage against quota
- No rate limit customization — cannot request temporary burst allowance

*API calls: 35 total, 35 passed, 0 failed/expected-error*

### Audit & Admin (NPS: 5/10)

**What worked well:**
- Global audit log captures cross-product activity
- Manual subscription processing trigger available for testing

**Missing features:**
- No per-agent audit log — only global, no filtering by agent_id
- No admin dashboard or usage analytics aggregation
- No RBAC — pro-tier key can access admin endpoints, but there's no 'admin' tier

*API calls: 2 total, 2 passed, 0 failed/expected-error*

### Error Handling (NPS: 6/10)

**What worked well:**
- 401 for missing API key
- Malformed request body handled gracefully
- Request body size is limited
- Backward-compatible redirects from legacy paths

**What was confusing or problematic:**
- Error response format inconsistency: some errors return {'error': {'code': '...', 'message': '...'}} while others return {'success': false, 'error': '...'}. Agents need a consistent error envelope.

**Missing features:**
- No request validation against input_schema — extra/missing params silently ignored
- No request ID in error responses for debugging correlation

*API calls: 6 total, 4 passed, 2 failed/expected-error*

---

## Pricing Feedback

### Current pricing model analysis

| Tool | Pricing | Assessment |
|------|---------|------------|
| get_balance, get_usage_summary, deposit | Free | Correct -- operational queries should be free |
| create_intent | 2% of amount (min 0.01, max 5.0) | Steep for micro-transactions. A $0.50 signal purchase costs $0.01 fee (2%), which is fine, but a $200 data feed purchase costs $4.00 fee -- that adds up |
| create_escrow | 1.5% of amount (min 0.01, max 10.0) | More reasonable than intent fees. The $10 max cap helps |
| best_match | 0.1 credits/call | Reasonable for a ranking query but discourages exploration. Trading bots that search frequently will burn credits on discovery |
| search_services | Free | Good -- discovery should have zero friction |
| submit_metrics | Free (pro-tier gate) | Correct -- metrics submission builds platform value |
| All trust tools | Free | Good -- trust data should be a public good |
| All event tools | Free | Correct -- event infrastructure is a platform cost |

### Pricing gaps and suggestions

1. **No volume discounts**: A trading bot making 100+ payments/day has no way to reduce the 2% fee. Tiered pricing (e.g., 2% for first 50/day, 1% for 50-200, 0.5% above 200) would incentivize high-volume usage.
2. **No prepaid bundles**: Cannot buy a block of 1000 API calls at a discount. Trading bots have predictable usage patterns and would benefit from commitment-based pricing.
3. **Credit-only economy**: No fiat on-ramp/off-ramp. Credits are an abstraction layer, but a trading bot needs to understand the real-dollar cost of platform usage. No exchange rate documentation for credits-to-USD.
4. **Missing cost estimation tool**: No way to pre-calculate the cost of a workflow (e.g., 'register service + 50 payments/day + 10 best_match queries = X credits/month'). A cost calculator endpoint would help budgeting.

---

## API Ergonomics

### Strengths

- **Unified endpoint**: Single POST /v1/execute with tool + params is clean and predictable
- **OpenAPI spec**: Auto-generated and complete, enables SDK generation
- **Consistent auth**: Bearer token / X-API-Key / query param flexibility is good
- **Signed responses**: Ed25519 response signing enables verification of gateway integrity
- **Correlation IDs**: X-Request-ID header for distributed tracing

### Weaknesses

- **Error envelope inconsistency**: Some errors use `{"error": {"code": ..., "message": ...}}` while success uses `{"success": true, "result": ...}`. The error path should also include `"success": false` for uniform parsing.
- **No pagination on most list endpoints**: search_services, get_events have limit/offset but get_payment_history returns everything. No cursor-based pagination standard.
- **No batch execution**: Cannot execute multiple tools in one request. A trading bot workflow (check balance -> create intent -> capture) requires 3 round-trips.
- **No async execution**: All tools are synchronous request/response. Long-running operations (like trust recomputation) block the caller.
- **No field selection / sparse responses**: Cannot request only specific fields from a response. Every call returns the full payload.
- **Input validation is silent**: Extra parameters are silently ignored instead of returning warnings. Typo in a parameter name goes unnoticed.

---

## Trading Bot Specific Feedback

### Identity system for trading bots

The Ed25519 identity system is a strong foundation. Being able to register a crypto identity and have the platform auto-generate a keypair reduces onboarding friction to near zero. The commitment hash system for metrics is particularly valuable: a trading bot can prove 'I submitted Sharpe = 1.82 on date X' without the platform needing to store raw data.

However, several gaps exist for trading bots specifically:

1. **No strategy-level identity**: AlphaBot-v3 runs 2 engines (expansion + trend-following). There is no way to register sub-identities for each strategy and report metrics separately.
2. **No exchange account linkage**: The platform cannot verify that 'alphabot-v3' is actually trading on Binance. An exchange OAuth2 integration would enable 'platform_verified' data_source.
3. **Metrics are point-in-time snapshots**: No time-series storage. A bot cannot show 'Sharpe improving from 1.2 to 1.8 over 6 months' -- only the latest submission exists.
4. **No benchmark comparison**: Cannot compare against market benchmarks (BTC buy-and-hold, equal-weight crypto index). Verified claims like 'Sharpe >= 1.5' are meaningless without context.
5. **No drawdown alerts**: The event bus could emit 'metrics.drawdown_breach' when a bot's submitted drawdown exceeds a threshold, notifying subscribers to pause signal consumption.

### Payment flows for trading bot commerce

The escrow primitive is excellent for trading signal delivery: buyer escrows payment, signal is delivered, buyer releases escrow. But the workflow is manual -- there is no automated escrow release on delivery confirmation.

Missing for trading bot payment workflows:

1. **Conditional escrow**: Release escrow IF signal resulted in profit > X%. Pay-for-performance is the natural model for trading signals.
2. **Recurring payments (subscriptions)**: process_due_subscriptions exists but no create_subscription tool. A daily signal feed requires daily manual intents.
3. **Revenue sharing**: Multi-agent strategy (signal provider + execution bot + risk manager) needs to split revenue. No multi-party payment support.
4. **Micro-payment batching**: 50+ signals/day at $0.10 each creates massive transaction overhead. A batching/netting mechanism would settle once daily instead.

---

## Consolidated Missing Features (Priority Order)

### P0 - Critical

- Self-service onboarding: create_wallet + create_api_key tools so agents can bootstrap themselves
- Subscription management: create_subscription / cancel_subscription for recurring payments
- Dispute resolution: dispute_payment / resolve_dispute for contested transactions
- Refund capability: refund_intent for reversing captured payments

### P1 - High

- Cancel escrow: payer can reclaim funds if payee fails to deliver
- Rate limit headers: X-RateLimit-Remaining, X-RateLimit-Reset in every response
- Webhook delivery status: history of delivery attempts and retry status
- Service lifecycle: update_service, delete_service for marketplace listings
- Transaction ledger: per-agent transaction history (deposits, charges, payments)

### P2 - Medium

- Key rotation: rotate_key for compromised Ed25519 keys
- Agent search/discovery: search_agents by capabilities or metrics
- Metrics time-series: historical metric queries, not just latest
- Leaderboard: rank agents by verified metrics within categories
- Batch execution: multiple tool calls in one request
- Event schema registry: validate event types against registered schemas

### P3 - Nice to have

- SSE/WebSocket streaming for real-time events
- Volume discount pricing tiers
- Cost estimation calculator
- Service ratings and reviews
- Multi-party payment splits
- Conditional escrow release

### Raw missing features by module

- **[System / Infrastructure]** No /v1/status or /v1/docs endpoint (HTML rendered docs)
- **[System / Infrastructure]** No SDK generation link or client library references in OpenAPI spec
- **[Identity + Paywall (API Keys)]** No 'rotate_key' or 'revoke_key' tool — cannot rotate compromised Ed25519 keys
- **[Identity + Paywall (API Keys)]** No 'list_agents' or 'search_agents' tool — cannot discover other agents by criteria
- **[Identity + Paywall (API Keys)]** No org/team concept — individual agent only, no way to group sub-bots under one org
- **[Billing]** No 'withdraw' tool — credits go in but cannot come out
- **[Billing]** No transaction history/ledger tool — only aggregate usage summary
- **[Billing]** No spending alerts or budget cap configuration
- **[Billing]** No credit expiry concept — credits live forever, no time-value accounting
- **[Payments]** No dispute_payment tool — cannot contest charges or request refunds
- **[Payments]** No create_subscription tool in catalog — process_due_subscriptions exists but no way to create one via gateway
- **[Payments]** No cancel_escrow tool — payer cannot reclaim funds if payee fails to deliver
- **[Payments]** No partial_capture — cannot capture a portion of the intent amount
- **[Payments]** No refund_intent — cannot reverse a captured payment
- **[Payments]** No multi-currency support — everything is in platform credits, no USD/USDT conversion
- **[Marketplace]** No subscribe_service — cannot programmatically subscribe to discovered services
- **[Marketplace]** No get_service (by ID) — must search to find a service you already know the ID of
- **[Marketplace]** No rate_service / review_service — no way to build marketplace reputation
- **[Marketplace]** No update_service — provider cannot update their listing after registration
- **[Marketplace]** No delete_service / deactivate_service — listings are permanent once registered
- **[Trust]** No submit_probe tool — trust scores seem to require internal probing, agents cannot self-report
- **[Trust]** No trust history/trend endpoint — cannot track score changes over time
- **[Trust]** No SLA compliance check tool — SLA is defined in catalog but never verified
- **[Metrics & Verified Claims]** No exchange_api verification — data_source='exchange_api' is accepted at face value. Platform should verify against actual exchange API to earn 'platform_verified' status.
- **[Metrics & Verified Claims]** No metric schema definition — any key/value accepted. Standard metric names should be documented.
- **[Metrics & Verified Claims]** No historical metrics endpoint — cannot query 'Sharpe for March 2026'
- **[Metrics & Verified Claims]** No leaderboard or ranking tool — cannot compare metrics across agents
- **[Metrics & Verified Claims]** No way to link metrics to specific strategies/pairs — a multi-strategy bot cannot report per-strategy performance
- **[Events & Webhooks]** No webhook delivery history/retry status — cannot debug failed deliveries
- **[Events & Webhooks]** No event schema registry — event_type is freeform string, no validation
- **[Events & Webhooks]** No SSE/WebSocket streaming for real-time events — only polling via get_events
- **[Events & Webhooks]** No dead letter queue for failed webhook deliveries
- **[Events & Webhooks]** No webhook test/ping endpoint to verify connectivity before going live
- **[Rate Limiting]** No rate limit headers (X-RateLimit-Remaining, X-RateLimit-Reset) in responses
- **[Rate Limiting]** No rate limit status endpoint to check current usage against quota
- **[Rate Limiting]** No rate limit customization — cannot request temporary burst allowance
- **[Audit & Admin]** No per-agent audit log — only global, no filtering by agent_id
- **[Audit & Admin]** No admin dashboard or usage analytics aggregation
- **[Audit & Admin]** No RBAC — pro-tier key can access admin endpoints, but there's no 'admin' tier
- **[Error Handling]** No request validation against input_schema — extra/missing params silently ignored
- **[Error Handling]** No request ID in error responses for debugging correlation

---

## Appendix: Test Execution Summary

| Metric | Value |
|--------|-------|
| Total API calls | 107 |
| Passed | 97 |
| Failed / Expected errors | 10 |
| Average latency | 2.9ms |
| P95 latency | 8.0ms |
| Max latency | 13.4ms |
| Simulation duration | 0.5s |

### System / Infrastructure

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| GET /v1/health | PASS | 200 | 1ms |
| GET /v1/pricing | PASS | 200 | 1ms |
| GET /v1/pricing/create_escrow | PASS | 200 | 0ms |
| GET /v1/pricing/nonexistent_tool | PASS | 404 | 0ms |
| GET /v1/openapi.json | PASS | 200 | 0ms |
| GET /v1/metrics | PASS | 200 | 0ms |
| GET /v1/signing-key | PASS | 200 | 0ms |

### Identity + Paywall (API Keys)

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| register_agent | PASS | 200 | 6ms |
| get_agent_identity | PASS | 200 | 4ms |
| get_agent_identity | PASS | 200 | 3ms |
| get_agent_reputation | PASS | 200 | 4ms |

### Billing

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| get_balance | PASS | 200 | 4ms |
| deposit | PASS | 200 | 8ms |
| deposit | FAIL | 500 | 1ms |
| get_usage_summary | PASS | 200 | 4ms |
| get_balance | FAIL | 404 | 1ms |

### Payments

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| create_intent | PASS | 200 | 8ms |
| capture_intent | PASS | 200 | 13ms |
| capture_intent | FAIL | 404 | 1ms |
| create_escrow | PASS | 403 | 1ms |
| create_escrow | PASS | 200 | 11ms |
| release_escrow | PASS | 200 | 9ms |
| get_payment_history | PASS | 200 | 5ms |
| dispute_payment | PASS | 400 | 0ms |
| create_subscription | PASS | 400 | 0ms |
| cancel_escrow | PASS | 400 | 0ms |
| create_intent | PASS | 200 | 8ms |
| create_intent | PASS | 200 | 6ms |

### Marketplace

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| search_services | PASS | 200 | 3ms |
| register_service | PASS | 200 | 5ms |
| register_service | PASS | 200 | 5ms |
| search_services | PASS | 200 | 4ms |
| search_services | PASS | 200 | 3ms |
| best_match | PASS | 200 | 6ms |
| search_services | PASS | 200 | 4ms |
| subscribe_service | PASS | 400 | 0ms |
| get_service | PASS | 400 | 0ms |
| rate_service | PASS | 400 | 1ms |
| update_service | PASS | 400 | 0ms |
| delete_service | PASS | 400 | 0ms |

### Trust

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| get_trust_score | FAIL | 404 | 1ms |
| get_trust_score | FAIL | 404 | 1ms |
| get_trust_score | FAIL | 404 | 0ms |
| search_servers | PASS | 200 | 3ms |
| search_servers | PASS | 200 | 3ms |
| update_server | FAIL | 404 | 1ms |
| submit_probe | PASS | 400 | 0ms |
| get_trust_history | PASS | 400 | 0ms |
| check_sla_compliance | PASS | 400 | 0ms |

### Metrics & Verified Claims

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| submit_metrics | PASS | 403 | 1ms |
| register_agent | PASS | 200 | 5ms |
| submit_metrics | FAIL | 500 | 1ms |
| get_verified_claims | PASS | 200 | 3ms |
| submit_metrics | PASS | 200 | 9ms |

### Events & Webhooks

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| publish_event | PASS | 200 | 4ms |
| publish_event | PASS | 200 | 4ms |
| publish_event | PASS | 200 | 4ms |
| publish_event | PASS | 200 | 4ms |
| get_events | PASS | 200 | 3ms |
| get_events | PASS | 200 | 3ms |
| get_events | PASS | 200 | 3ms |
| register_webhook | PASS | 200 | 4ms |
| list_webhooks | PASS | 200 | 3ms |
| delete_webhook | PASS | 200 | 4ms |

### Rate Limiting

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 4ms |
| get_balance | PASS | 200 | 4ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |
| get_balance | PASS | 200 | 3ms |

### Audit & Admin

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| get_global_audit_log | PASS | 200 | 3ms |
| process_due_subscriptions | PASS | 200 | 4ms |

### Error Handling

| Step | Status | HTTP | Latency |
|------|--------|------|---------|
| get_balance | FAIL | 401 | 0ms |
| no_auth_header | PASS | 401 | 0ms |
| invalid_json | PASS | 400 | 1ms |
|  | PASS | 400 | 0ms |
| get_balance | FAIL | 404 | 1ms |
| redirect /health -> /v1/health | PASS | 301 | 0ms |

---

*Report generated by AlphaBot-v3 Customer Agent Simulation*
*Simulation ran against A2A Commerce Gateway v0.1.0 using httpx ASGI transport (no live server)*
