# PRD 011: Cryptographic Signing for Agent Metric Submissions

**Status:** Draft
**Author:** Platform Team
**Date:** 2026-03-29

## Problem

Agent metric submissions need cryptographic integrity guarantees. Currently the platform auditor signs attestations, but agent-side submissions are unsigned — any party with the agent_id can submit metrics on their behalf.

## Current Architecture

```
Agent submits metrics (unsigned)
    → Platform creates hiding commitments (SHA3-256)
    → Platform auditor signs commitment batch (Ed25519)
    → Attestation stored with auditor signature
```

**Gap:** No proof that the agent itself authorized the submission.

## Proposed Architecture

```
Agent signs submission payload with its Ed25519 private key
    → Platform verifies agent signature
    → Platform creates hiding commitments (SHA3-256)
    → Platform auditor co-signs commitment batch
    → Dual-signed attestation stored
```

## Design

### 1. Submission Signing Protocol

The agent signs a canonical payload before submission:

```python
# Agent-side
payload = {
    "agent_id": "agent-7f3a2b",
    "metrics": {"sharpe_30d": 2.35, "max_drawdown_30d": 3.1},
    "timestamp": 1711612800.0,
    "nonce": "a1b2c3d4"  # Replay protection
}
canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
signature = ed25519_sign(agent_private_key, canonical.encode())
```

### 2. Submission Verification

```python
# Platform-side (in IdentityAPI.submit_metrics)
def verify_submission(agent_id, payload, signature):
    identity = storage.get_identity(agent_id)
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return AgentCrypto.verify(identity.public_key, canonical.encode(), signature)
```

### 3. API Changes

`submit_metrics` gains two optional parameters (optional for backward compatibility):

```python
async def submit_metrics(
    self,
    agent_id: str,
    metrics: dict[str, float],
    data_source: str = "self_reported",
    signature: str | None = None,      # NEW: agent's Ed25519 signature
    nonce: str | None = None,           # NEW: replay protection
) -> MetricSubmissionResult:
```

If `signature` is provided:
- Platform verifies against stored public key
- Attestation `data_source` auto-upgrades to `"agent_signed"`
- Nonce is checked against a recent-nonce cache (5-minute TTL)

If `signature` is omitted:
- Backward compatible: works as before
- `data_source` cannot exceed `"self_reported"` tier

### 4. Nonce Management

```sql
CREATE TABLE submission_nonces (
    nonce TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    used_at REAL NOT NULL
);
-- Periodic cleanup: DELETE WHERE used_at < now() - 300
```

### 5. Data Source Trust Tiers

| Tier | Description | Reputation Weight |
|------|-------------|------------------|
| `platform_verified` | Platform-computed from exchange data | 1.0 |
| `exchange_api` | Agent-submitted with exchange API proof | 0.7 |
| `agent_signed` | Agent-submitted with Ed25519 signature | 0.5 |
| `self_reported` | Unsigned submission (legacy) | 0.4 |

### 6. Key Rotation Compatibility

When an agent rotates keys via `rotate_key`, old submissions remain valid because attestations reference the auditor signature (not the agent key). New submissions must use the current key.

## Security Considerations

1. **Replay attacks**: Nonce + 5-minute TTL window
2. **Key compromise**: Agent can rotate key; old attestations remain valid via auditor co-signature
3. **Timestamp manipulation**: Platform uses server-side `time.time()`, ignores agent-provided timestamp for attestation
4. **Canonical encoding**: `json.dumps(sort_keys=True, separators=(',', ':'))` ensures deterministic serialization

## Migration Path

1. Add `signature` and `nonce` columns to submission API (optional)
2. Add `submission_nonces` table via migration
3. Update reputation scoring to weight `agent_signed` higher than `self_reported`
4. Eventually deprecate unsigned submissions (6-month timeline)
