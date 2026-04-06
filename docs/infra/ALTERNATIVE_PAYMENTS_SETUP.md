# Setting Up Alternative Payment Methods for Live Testing

**Audience:** Human operator preparing wallets and payment methods for the external auditor.
**Date:** 2026-04-06

---

## Current Payment Methods

| Method | Status | How It Works |
|--------|--------|-------------|
| **Stripe (fiat)** | Live on prod | Agent calls `POST /v1/checkout` -> pays in browser -> webhook deposits credits |
| **x402 (crypto)** | Live on prod | Agent sends signed USDC authorization in `X-Payment` header -> pays per-call |

---

## 1. Stripe (Credit Card) — Already Working

### Quick test

```bash
# Create checkout session
API_KEY="a2a_free_527c5a16f3515a11e2f89b10"
curl -s -X POST https://api.greenhelix.net/v1/checkout \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"package": "starter"}' | jq .

# Copy checkout_url, open in browser, pay with card
# After ~10s, verify balance increased by 1000:
curl -s -H "Authorization: Bearer $API_KEY" \
  "https://api.greenhelix.net/v1/billing/wallets/audit-payer-prod-1775375850/balance" | jq .
```

### Packages

| Package | Credits | Price |
|---------|---------|-------|
| starter | 1,000 | $10 |
| growth | 5,000 | $45 |
| scale | 25,000 | $200 |
| enterprise | 100,000 | $750 |

Custom: `{"credits": 500}` -> $5.00 (minimum 100 credits).

### Test cards (sandbox only)

| Card | Behavior |
|------|----------|
| `4242 4242 4242 4242` | Succeeds |
| `4000 0000 0000 0002` | Always declined |
| `4000 0025 0000 3155` | Requires 3DS |

Use any future expiry, any CVC, any ZIP.

---

## 2. x402 Protocol (USDC Crypto Payments) — Already Enabled

The platform supports **payment-as-authentication** via the [x402 protocol](https://x402.org). Agents pay per-call in USDC without needing an API key or wallet account.

### Current production config

```
X402_ENABLED=true
X402_MERCHANT_ADDRESS=0x27f9987473cB18596521dFf30B026E4eb386b19C
X402_FACILITATOR_URL=https://x402.org/facilitator
X402_SUPPORTED_NETWORKS=base,polygon
```

### How it works

1. Client calls `POST /v1/execute` **without** an API key
2. Gateway returns **HTTP 402** with payment challenge:
   ```json
   {
     "max_amount_required": "100000",
     "pay_to": "0x27f9987473cB18596521dFf30B026E4eb386b19C",
     "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
     "network": "base"
   }
   ```
   (Amount in USDC smallest units: 6 decimals, so 100000 = $0.10)
3. Client signs an EIP-3009 transfer authorization
4. Client retries with `X-Payment: <base64-encoded proof>` header
5. Gateway verifies locally + via Coinbase Facilitator, then executes the tool
6. Settlement happens on-chain (USDC transferred from payer to merchant)

### Setting up a crypto wallet for testing

#### Option A: Use Coinbase Wallet (easiest)

1. Install [Coinbase Wallet](https://www.coinbase.com/wallet) browser extension or mobile app
2. Fund with USDC on **Base** network:
   - Buy USDC on Coinbase -> Send to your Coinbase Wallet on Base
   - Or bridge from Ethereum mainnet using the [Base Bridge](https://bridge.base.org)
3. You'll need the wallet's private key to sign EIP-3009 authorizations

#### Option B: Use MetaMask

1. Install [MetaMask](https://metamask.io)
2. Add **Base** network:
   - Network Name: `Base`
   - RPC URL: `https://mainnet.base.org`
   - Chain ID: `8453`
   - Currency: `ETH`
   - Explorer: `https://basescan.org`
3. Add USDC token: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
4. Fund with USDC (bridge from Coinbase or another chain)
5. You also need a small amount of ETH on Base for gas (bridging/approvals)

#### Option C: Use a programmatic wallet (for automated testing)

```bash
# Install the Coinbase CDP SDK (or use ethers.js / web3.py)
pip install cdp-sdk

# Or use the x402 TypeScript SDK
npm install x402
```

Example with the x402 SDK (TypeScript):
```typescript
import { createX402Client } from "x402";

const client = createX402Client({
  privateKey: process.env.WALLET_PRIVATE_KEY,
  network: "base",
});

const result = await client.request("https://api.greenhelix.net/v1/execute", {
  method: "POST",
  body: JSON.stringify({
    tool: "get_balance",
    params: { agent_id: "some-agent" }
  }),
});
```

### USDC contract addresses

| Network | USDC Contract |
|---------|--------------|
| Base | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Polygon | `0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359` |

### Key differences from Stripe

| | Stripe | x402 |
|---|--------|------|
| **Auth** | API key required | No API key needed |
| **Payment** | Pre-pay (buy credits) | Pay-per-call (USDC) |
| **Wallet** | Credits deposited to internal wallet | No internal wallet; on-chain settlement |
| **Identity** | `agent_id` from registration | Wallet address (e.g., `0x1234...`) |
| **Tier** | free/pro/enterprise | `x402` (no tier restrictions) |
| **Refunds** | Via Stripe dashboard | N/A (atomic per-call) |

---

## 3. Testing Checklist for the Auditor

### Stripe tests (Phase 7 of audit)

- [ ] Create checkout session (`POST /v1/checkout`)
- [ ] Complete payment in browser
- [ ] Verify wallet balance increased
- [ ] Verify transaction history shows Stripe deposit
- [ ] Test declined card (balance unchanged)
- [ ] Test forged webhook (rejected, balance unchanged)

### x402 tests

- [ ] Send request without API key or payment -> expect 402
- [ ] Verify 402 response includes correct payment challenge fields
- [ ] Send request with valid x402 payment proof -> expect 200 + tool result
- [ ] Send request with replayed nonce -> expect 402 (replay detected)
- [ ] Verify on-chain USDC settlement (check merchant wallet on basescan.org)
- [ ] Verify usage recorded under wallet address agent_id

### Budget

| Method | Budget Cap |
|--------|-----------|
| Stripe (prod) | $10 USD max |
| x402 (prod) | $10 USDC max |
| Total | $20 USD equivalent |

---

## 4. Merchant Wallet Verification

The merchant wallet receiving x402 payments can be verified on-chain:

```
Merchant: 0x27f9987473cB18596521dFf30B026E4eb386b19C
Base Explorer: https://basescan.org/address/0x27f9987473cB18596521dFf30B026E4eb386b19C
Polygon Explorer: https://polygonscan.com/address/0x27f9987473cB18596521dFf30B026E4eb386b19C
```

All x402 settlements are visible on-chain for full auditability.
