# Task: Create OpenClaw Skill — Formal Gatekeeper Usage Guide

## Role
You are a Technical Writer and AI Skill Designer specializing in developer-facing documentation for autonomous agent platforms. You write clear, actionable guides that AI agents can follow without human intervention.

## Objective
Create a comprehensive OpenClaw skill (SKILL.md) that teaches AI agents how to use the **Formal Gatekeeper** service on the GreenHelix A2A Commerce Platform. The skill should serve as a complete reference and decision guide — covering what the service does, when to use it, how to call each endpoint, and how to interpret results.

## Platform Context

The Formal Gatekeeper is a formal verification service. Agents submit Z3 SMT-LIB2 workflow plans and receive cryptographic proofs that safety properties hold. Use cases:

- **Pre-trade verification**: Prove that a payment workflow preserves balance invariants before executing it
- **Escrow-gated release**: Attach a verification proof to an escrow so funds only release when safety properties are satisfied
- **Compliance attestation**: Generate verifiable proofs that a workflow meets economic or contractual constraints
- **Trust building**: Publish proof hashes so other agents can independently verify your claims

## API Reference

**Base URL**: `https://api.greenhelix.net`
**Authentication**: API key via `Authorization: Bearer <key>` header
**Tier required**: `pro` (except `verify_proof` which is `free`)

### Endpoints

#### 1. Submit Verification Job
```
POST /v1/gatekeeper/jobs
```
**Cost**: 5 credits base + 1 credit per property
**Request body**:
```json
{
  "agent_id": "agent-alice",
  "properties": [
    {
      "name": "balance_conservation",
      "scope": "economic",
      "language": "z3_smt2",
      "expression": "(declare-const sender_before Int)\n(declare-const sender_after Int)\n(declare-const receiver_before Int)\n(declare-const receiver_after Int)\n(declare-const amount Int)\n(assert (> amount 0))\n(assert (= sender_after (- sender_before amount)))\n(assert (= receiver_after (+ receiver_before amount)))\n(assert (= (+ sender_after receiver_after) (+ sender_before receiver_before)))",
      "description": "Verify that a transfer preserves total balance"
    }
  ],
  "scope": "economic",
  "timeout_seconds": 300,
  "webhook_url": null,
  "idempotency_key": "unique-request-id-001",
  "metadata": {"workflow": "escrow-release", "intent_id": "pi-abc123"}
}
```
**Response** (201):
```json
{
  "job_id": "vj-a1b2c3d4e5f6",
  "status": "completed",
  "cost": "6.0",
  "created_at": 1711612800.0
}
```

#### 2. Get Verification Status
```
GET /v1/gatekeeper/jobs/{job_id}
```
**Cost**: Free
**Response**:
```json
{
  "job_id": "vj-a1b2c3d4e5f6",
  "agent_id": "agent-alice",
  "status": "completed",
  "result": "satisfied",
  "proof_artifact_id": "pf-x1y2z3",
  "cost": "6.0",
  "created_at": 1711612800.0,
  "updated_at": 1711612842.0
}
```
**Status values**: `pending`, `running`, `completed`, `failed`, `timeout`, `cancelled`
**Result values**: `satisfied` (safe), `violated` (unsafe — counterexample available), `unknown`, `error`

#### 3. List Verification Jobs
```
GET /v1/gatekeeper/jobs?agent_id=agent-alice&status=completed&limit=10
```
**Cost**: Free
**Query params**: `agent_id` (required), `status` (optional filter), `limit` (default 50), `cursor` (pagination)

#### 4. Cancel Verification
```
POST /v1/gatekeeper/jobs/{job_id}/cancel
```
**Cost**: Free. Only works on `pending` or `running` jobs.

#### 5. Get Proof Artifact
```
GET /v1/gatekeeper/proofs/{proof_id}
```
**Cost**: Free
**Response**:
```json
{
  "proof_id": "pf-x1y2z3",
  "job_id": "vj-a1b2c3d4e5f6",
  "agent_id": "agent-alice",
  "result": "satisfied",
  "proof_hash": "a1b2c3...64-char-sha3-256-hex",
  "valid_until": 1714204800.0,
  "property_results": [
    {"name": "balance_conservation", "result": "satisfied", "model": "[amount = 1, ...]"}
  ],
  "created_at": 1711612842.0
}
```

#### 6. Verify Proof (Public — Free Tier)
```
POST /v1/gatekeeper/proofs/verify
```
**Cost**: Free. **No authentication required for free-tier agents.**
**Request body**:
```json
{
  "proof_hash": "a1b2c3...64-char-sha3-256-hex"
}
```
**Response** (valid):
```json
{
  "valid": true,
  "proof_id": "pf-x1y2z3",
  "job_id": "vj-a1b2c3d4e5f6",
  "agent_id": "agent-alice",
  "result": "satisfied",
  "valid_until": 1714204800.0
}
```
**Response** (invalid):
```json
{
  "valid": false,
  "reason": "proof_not_found"
}
```
Possible reasons: `proof_not_found`, `proof_expired`, `hash_mismatch`

## Verification Scopes

| Scope | Use Case |
|-------|----------|
| `economic` | Balance conservation, deposit limits, fee calculations |
| `workflow` | State machine correctness, step ordering, preconditions |
| `network` | Connection constraints, IP whitelisting, rate bounds |
| `contract` | SLA compliance, contractual obligation fulfillment |

## Z3 SMT-LIB2 Primer

The `expression` field uses Z3's SMT-LIB2 syntax. Key constructs:

```smt2
; Declare variables
(declare-const x Int)
(declare-const y Real)
(declare-const flag Bool)

; Assert constraints
(assert (> x 0))
(assert (= y 3.14))
(assert (=> flag (< x 100)))

; The solver checks if ALL assertions can be satisfied simultaneously
; SAT = all constraints can hold (property satisfied)
; UNSAT = constraints are contradictory (property violated)
```

## Scenarios to Cover in the Skill

The skill MUST include worked examples for each of these scenarios:

### Scenario 1: Pre-Payment Safety Check
An agent wants to verify that a 3-party split payment preserves total balances before executing it. Show the full flow: construct properties → submit → poll → interpret result.

### Scenario 2: Escrow-Gated Release
An agent creates a performance escrow with a `verification_job_id` in the metadata. Show how to: submit verification → attach proof to escrow → release only if `result == "satisfied"`.

### Scenario 3: Counterexample Analysis
A verification returns `violated`. Show how to: read the counterexample from `property_results` → understand what input breaks the invariant → fix the workflow → re-submit.

### Scenario 4: Cross-Agent Proof Sharing
Agent A generates a proof of economic safety. Agent B (a counterparty) independently verifies it using the free `verify_proof` endpoint before agreeing to a transaction. Show both sides.

### Scenario 5: Batch Verification with Idempotency
An agent needs to verify multiple properties across different scopes. Show how to use `idempotency_key` to safely retry failed submissions without double-charging.

### Scenario 6: Timeout and Error Handling
Show how to handle: `timeout` status (increase `timeout_seconds` or simplify formula), `error` status (fix SMT syntax), `failed` status (Lambda backend unavailable — retry later).

## Skill Deliverables

1. **`SKILL.md`** — The main skill file. Must follow OpenClaw skill format:
   - `## Identity` — name, version, description
   - `## Capabilities` — what the skill can do
   - `## Instructions` — step-by-step decision tree for the agent
   - `## Examples` — the 6 scenarios above with full HTTP request/response pairs
   - `## Error Reference` — every error code and what to do about it
   - `## Pricing` — cost breakdown so the agent can budget

2. **`manifest.json`** — Skill metadata:
   ```json
   {
     "name": "formal-gatekeeper-guide",
     "version": "1.0.0",
     "description": "Guide for using the Formal Gatekeeper verification service",
     "author": "greenhelix",
     "tier_required": "free",
     "tools_referenced": [
       "submit_verification",
       "get_verification_status",
       "list_verification_jobs",
       "cancel_verification",
       "get_proof",
       "verify_proof"
     ]
   }
   ```

## Quality Requirements

- Every code example must be copy-pasteable (valid JSON, valid SMT-LIB2)
- Include both `curl` examples and structured JSON request/response pairs
- Explain the Z3 result semantics clearly: SAT means the constraints CAN be satisfied (property holds), UNSAT means they CANNOT (property violated — the system found a counterexample proving it)
- The skill must be usable by an agent with zero prior Z3 knowledge
- Include a "Quick Start" section that gets an agent from zero to first proof in under 5 API calls
- Proofs expire after 30 days — mention this prominently
