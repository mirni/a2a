# PRD-006: Connector Subscription & Paywall Integration

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

Our 3 production connectors exist but generate no revenue. The billing layer exists but isn't wired into any product. We need to connect them: agents that use our connectors should be metered, and premium features should be gated behind subscriptions.

## Target Buyer

- Same as connector buyers: agent developers, startups, trading bot builders
- Self-serve: no sales cycle, sign up and get API key

## Product Scope

### Tiered Access Model

**Free Tier** (open-source core):
- All tools available
- Rate limited: 100 calls/hour per agent
- No SLA, no support
- No audit logs retained

**Pro Tier** ($29-49/month per connector):
- Unlimited calls (fair use)
- Rate limited: 10,000 calls/hour
- Audit log retention (30 days)
- Priority retry (more aggressive retry config)
- Usage dashboard

### Implementation

A `PaywallMiddleware` that wraps any MCP server:

```python
from a2a_billing import UsageTracker
from a2a_paywall import PaywallMiddleware

tracker = UsageTracker(storage="sqlite:///billing.db")
middleware = PaywallMiddleware(tracker=tracker, connector="stripe")

# Wraps tool calls: check agent wallet, meter usage, enforce tier limits
@middleware.gated(tier="pro", cost=1)
async def create_payment_intent(params):
    ...
```

### Components

- **PaywallMiddleware** — decorator/wrapper that intercepts MCP tool calls
  - Extracts agent_id from request context
  - Checks agent tier (free/pro/enterprise)
  - Enforces tier-specific rate limits
  - Meters usage via billing layer
  - Returns structured error on quota exceeded

- **API Key Management** — simple key-based auth for agents
  - `POST /v1/keys/create` — create API key tied to agent wallet
  - Keys map to agent_id in billing system
  - Keys carry tier information

- **Usage Dashboard API** — agents query their own usage
  - `GET /v1/usage/summary` — current period usage
  - `GET /v1/usage/history` — historical usage
  - `GET /v1/usage/projected` — projected end-of-period cost

## Pricing Hypothesis

| Connector | Free | Pro |
|-----------|------|-----|
| Stripe | 100 calls/hr | $49/mo unlimited |
| PostgreSQL | 100 calls/hr | $39/mo unlimited |
| GitHub | 100 calls/hr | $29/mo unlimited |
| Bundle (all 3) | 100 calls/hr each | $99/mo unlimited |

## Success Metrics

- 20+ free tier sign-ups in 30 days
- 5+ paid conversions in 60 days
- <50ms overhead per metered call

## Kill Criteria

- <5 free sign-ups in 30 days → product/marketing problem
- 0 paid conversions in 90 days → pricing or value proposition problem
