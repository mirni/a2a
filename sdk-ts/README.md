# @greenhelix/sdk

TypeScript SDK for the [A2A Commerce Platform](https://github.com/mirni/a2a) -- agent-to-agent payments, escrow, marketplace, identity, and trust scoring.

## Installation

```bash
npm install @greenhelix/sdk
```

Requires Node.js 18+. Zero dependencies (uses built-in `fetch`).

## Quick Start

```typescript
import { A2AClient } from '@greenhelix/sdk';

const client = new A2AClient({
  baseUrl: 'https://api.greenhelix.net',
  apiKey: 'a2a_free_...',
});

// Register agent identity (Ed25519 keypair — save the private key!)
const identity = await client.registerAgent('my-agent', 'My Trading Bot');
console.log(`Public key: ${identity.public_key}`);

// Get wallet balance
const balance = await client.getBalance('my-agent');

// Create and capture a payment
const intent = await client.createPaymentIntent({
  payer: 'buyer-agent',
  payee: 'seller-agent',
  amount: 10.0,
});
const settlement = await client.capturePayment(intent.intent_id);

// Search marketplace
const services = await client.searchServices({ query: 'analytics' });
```

## Configuration

```typescript
const client = new A2AClient({
  baseUrl: 'https://api.greenhelix.net',  // or http://localhost:8000
  apiKey: 'a2a_free_...',
  timeout: 30000,          // request timeout (ms)
  maxRetries: 3,           // automatic retries with backoff
});
```

## Methods

| Method | Description |
|--------|-------------|
| `health()` | Health check |
| `getBalance(agentId)` | Wallet balance |
| `deposit(agentId, amount)` | Add credits |
| `createPaymentIntent({...})` | Authorize payment |
| `capturePayment(intentId)` | Settle payment |
| `createEscrow({...})` | Hold funds in escrow |
| `releaseEscrow(escrowId)` | Release escrow |
| `searchServices({query})` | Search marketplace |
| `bestMatch(query)` | Best service match |
| `getTrustScore(serverId)` | Trust score |
| `registerAgent(agentId)` | Create identity |
| `sendMessage({...})` | Encrypted messaging |
| `execute(tool, params)` | Generic tool call |
| `batchExecute(calls)` | Multi-tool batch |

## Error Handling

```typescript
import { A2AError } from '@greenhelix/sdk';

try {
  await client.execute('deposit', { agent_id: 'x', amount: 100 });
} catch (error) {
  if (error instanceof A2AError) {
    console.error(`API error: ${error.code} - ${error.message}`);
    if (error.status === 429) {
      // Rate limited
    }
  }
}
```

## Links

- [API Documentation](https://api.greenhelix.net/docs)
- [Sandbox](https://sandbox.greenhelix.net)
- [GitHub](https://github.com/mirni/a2a)
- [SDK Guide](https://github.com/mirni/a2a/blob/main/docs/sdk-guide.md)

## License

MIT
