# Agent Billing & Usage Tracking Layer

Credit-based billing infrastructure for A2A commerce. Provides usage metering, agent wallets, rate policies, and billing event streams for MCP server monetization.

## Components

| Component | Description |
|-----------|-------------|
| `UsageTracker` | Main entry point — meters calls, tokens, and custom metrics per agent |
| `Wallet` | Credit-based accounts with deposit/withdraw/charge/balance |
| `RatePolicyManager` | Per-agent rate limits (calls/min) and spend caps (credits/day) |
| `BillingEventStream` | Push + pull event stream for external billing integration |

## Quick Start

```python
from a2a_billing import UsageTracker, require_credits

# Initialize with SQLite storage
async with UsageTracker(storage="sqlite:///billing.db") as tracker:

    # Meter any async function
    @tracker.metered(cost=1)
    async def my_tool(agent_id: str, params: dict):
        return {"result": "ok"}

    # Or require wallet balance
    @require_credits(tracker, cost=5)
    async def premium_tool(agent_id: str, params: dict):
        return {"result": "premium"}

    # Call the function — billing happens automatically
    result = await my_tool(agent_id="agent-123", params={})
```

## Wallet Operations

```python
from a2a_billing import Wallet, StorageBackend

storage = StorageBackend("sqlite:///billing.db")
await storage.connect()
wallet = Wallet(storage)

# Create wallet with initial balance
await wallet.create("agent-123", initial_balance=100.0)

# Check balance
balance = await wallet.get_balance("agent-123")  # 100.0

# Deposit credits
await wallet.deposit("agent-123", amount=50.0)   # 150.0

# Charge for usage
await wallet.charge("agent-123", amount=10.0)     # 140.0

# View transaction history
txns = await wallet.get_transactions("agent-123")
```

## Rate Policies

```python
from a2a_billing import RatePolicyManager

policies = RatePolicyManager(storage)

# Set limits: 60 calls/min, 1000 credits/day
await policies.set_policy("agent-123", max_calls_per_min=60, max_spend_per_day=1000)

# Check before allowing a call
await policies.check_all("agent-123", cost=1)  # raises if limit exceeded
```

## Billing Events

```python
from a2a_billing import BillingEventStream

events = BillingEventStream(storage)

# Push pattern: register handler
@events.on_event
async def handle_event(event):
    print(f"Agent {event['agent_id']} used {event['payload']['cost']} credits")

# Pull pattern: poll for pending events
pending = await events.get_pending(limit=100)
for event in pending:
    process(event)
    await events.acknowledge(event["id"])
```

## Storage

All data is stored in SQLite via `aiosqlite`. Tables are auto-created on first connect:

- `wallets` — agent credit balances
- `usage_records` — per-call metering records
- `transactions` — deposit/withdrawal/charge ledger
- `rate_policies` — per-agent rate limits and spend caps
- `billing_events` — persistent event stream with delivery tracking
