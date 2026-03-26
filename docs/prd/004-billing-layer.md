# PRD-004: Agent Billing & Usage Tracking Layer

**Date**: 2026-03-26
**Role**: CPO
**Status**: Approved for build

## Problem Statement

There is no standard way for MCP servers to meter usage, track costs, or bill consuming agents. Server operators cannot monetize their tools. Consuming agents cannot budget or track spend. This is the foundational gap preventing A2A commerce.

## Target Buyer

- MCP server developers wanting to monetize
- Agent developers wanting usage visibility and cost control
- Our own connectors (dogfooding — billing layer wraps our connectors)

## Product Scope

A lightweight Python library + API for usage metering and billing:

### Components
- **Usage tracker**: Middleware that counts calls, tokens, and custom metrics per agent
- **Agent wallets**: Credit-based accounts with deposit/withdraw/balance operations
- **Rate policies**: Configurable per-agent rate limits and spend caps
- **Usage API**: Query usage history, current balance, projected costs
- **Billing events**: Webhook-compatible event stream for external billing systems

### Integration Pattern
```python
from a2a_billing import UsageTracker, require_credits

tracker = UsageTracker(storage="sqlite:///billing.db")

@tracker.metered(cost=1)  # 1 credit per call
async def my_tool_handler(params):
    ...
```

### What It Is NOT (v1)
- Not a payment processor (no real money movement in v1)
- Not a subscription manager (that's Phase 2)
- Not a marketplace (that's Phase 3)

## Pricing Hypothesis

- Free and open-source (this is infrastructure — monetize via adoption, not license)
- Revenue comes from our connectors using it + consulting for custom deployments

## Success Metrics

- 3+ external MCP servers adopt the library in 60 days
- Our 3 connectors all use it (dogfooding)
- <5ms overhead per metered call

## Kill Criteria

- Zero external adoption in 90 days → simplify to internal-only usage tracker
- >20ms overhead per metered call → architectural rethink needed
