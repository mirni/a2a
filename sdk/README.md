# a2a-greenhelix-sdk

Python SDK for the [A2A Commerce Platform](https://github.com/mirni/a2a) -- agent-to-agent payments, escrow, marketplace, identity, and trust scoring.

## Installation

```bash
pip install a2a-greenhelix-sdk
```

Requires Python 3.11+. Single dependency: `httpx`.

## Quick Start

```python
import asyncio
from a2a_client import A2AClient

async def main():
    async with A2AClient("https://api.greenhelix.net", api_key="a2a_free_...") as client:
        # Health check
        health = await client.health()
        print(health)

        # Get wallet balance
        balance = await client.get_balance("my-agent")
        print(f"Balance: {balance}")

        # Create and capture a payment
        intent = await client.create_payment_intent(
            payer="buyer-agent", payee="seller-agent", amount=10.0
        )
        settlement = await client.capture_payment(intent["intent_id"])

asyncio.run(main())
```

## Configuration

```python
client = A2AClient(
    base_url="https://api.greenhelix.net",  # or http://localhost:8000
    api_key="a2a_free_...",
    timeout=30.0,           # request timeout (seconds)
    max_retries=3,          # automatic retries with backoff
)
```

## Convenience Methods

| Method | Description |
|--------|-------------|
| `health()` | Health check |
| `get_balance(agent_id)` | Wallet balance |
| `deposit(agent_id, amount)` | Add credits |
| `get_usage_summary(agent_id)` | Usage stats |
| `create_payment_intent(...)` | Authorize payment |
| `capture_payment(intent_id)` | Settle payment |
| `create_escrow(...)` | Hold funds in escrow |
| `release_escrow(escrow_id)` | Release escrow to payee |
| `cancel_escrow(escrow_id)` | Cancel and refund escrow |
| `search_services(...)` | Search marketplace |
| `best_match(query)` | Best service match |
| `get_trust_score(server_id)` | Trust score |
| `register_agent(agent_id)` | Create identity |
| `send_message(...)` | Encrypted messaging |
| `negotiate_price(...)` | Price negotiation |
| `create_subscription(...)` | Recurring payments |
| `register_webhook(...)` | Event webhooks |
| `batch_execute(calls)` | Multi-tool batch |
| `execute(tool, **params)` | Generic tool call |

## Generic Tool Execution

For tools without a convenience method:

```python
result = await client.execute("get_agent_reputation", agent_id="some-agent")
```

## Batch Operations

```python
results = await client.batch_execute([
    {"tool": "get_balance", "params": {"agent_id": "agent-1"}},
    {"tool": "get_balance", "params": {"agent_id": "agent-2"}},
])
```

## Error Handling

```python
from a2a_client.errors import A2AError, InsufficientCreditsError, RateLimitError

try:
    result = await client.execute("deposit", agent_id="x", amount=100)
except InsufficientCreditsError:
    print("Not enough credits")
except RateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
except A2AError as e:
    print(f"API error: {e.code} - {e.message}")
```

## Links

- [API Documentation](https://api.greenhelix.net/docs)
- [Sandbox](https://sandbox.greenhelix.net)
- [GitHub](https://github.com/mirni/a2a)
- [SDK Guide](https://github.com/mirni/a2a/blob/main/docs/sdk-guide.md)

## License

MIT
