# Fix /v1/register Returning 500 on Sandbox

**Priority:** BLOCKER (B5)
**Source:** Market Readiness Audit 2026-04-01
**Effort:** 1 day

## Problem

`POST /v1/register` on `api.greenhelix.net` returns HTTP 500.
- Agent creation succeeds (409 on retry confirms agent exists)
- Failure appears to be in downstream wallet creation or API key generation
- This is the **first API call** a new developer makes — critical for onboarding

## Steps to Reproduce

```bash
curl -X POST https://api.greenhelix.net/v1/register \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test-agent-new", "name": "Test"}'
# Returns 500, but agent is created (subsequent call returns 409)
```

## Acceptance Criteria
- [ ] `POST /v1/register` returns 200 with `{api_key, agent_id, credits}` on sandbox
- [ ] Wallet is created with 500 credit signup bonus
- [ ] API key is generated and returned
- [ ] Idempotent: re-registration returns 409 with clear message
