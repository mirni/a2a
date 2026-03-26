# Stripe MCP Connector

Production-grade MCP server for Stripe with idempotency, retry, rate limiting, and structured errors.

## Tools

| Tool | Description |
|------|-------------|
| `create_customer` | Create customer with dedup (idempotency key) |
| `create_payment_intent` | Idempotent payment creation |
| `list_charges` | Paginated charge listing with filters |
| `create_subscription` | Subscription lifecycle management |
| `get_balance` | Account balance retrieval |
| `create_refund` | Idempotent refund processing |
| `list_invoices` | Invoice listing with filters |

## Quick Start

```bash
# Set your Stripe API key
export STRIPE_API_KEY=sk_test_...

# Run the MCP server
python -m src.server
```

## Configuration

| Env Variable | Required | Description |
|-------------|----------|-------------|
| `STRIPE_API_KEY` | Yes | Stripe secret key (sk_test_* or sk_live_*) |

## Production Guarantees

- **Idempotency**: All write operations require and use idempotency keys
- **Retry**: Exponential backoff on 429 and 5xx (configurable max_retries, base_delay)
- **Rate limiting**: Token bucket respects Stripe's rate limits and Retry-After headers
- **Validation**: Pydantic models validate all inputs before API calls
- **Audit**: Every operation logged with timestamp, params (secrets redacted), duration, result
- **Errors**: Machine-readable error codes (AUTH_ERROR, RATE_LIMIT, UPSTREAM_ERROR, VALIDATION_ERROR, TIMEOUT)

## Example Usage (from an agent)

```json
{
  "tool": "create_payment_intent",
  "arguments": {
    "amount": 2000,
    "currency": "usd",
    "idempotency_key": "order-12345",
    "customer_id": "cus_abc123",
    "description": "Order #12345"
  }
}
```

Response:
```json
{
  "success": true,
  "data": {
    "id": "pi_xyz",
    "amount": 2000,
    "currency": "usd",
    "status": "requires_payment_method"
  }
}
```

## Error Response Format

```json
{
  "success": false,
  "error": {
    "error": true,
    "code": "RATE_LIMIT",
    "message": "Rate limit exceeded",
    "retryable": true,
    "details": {"retry_after": 2.0}
  }
}
```
