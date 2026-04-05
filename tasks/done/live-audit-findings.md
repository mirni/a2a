# Prompt

## Process the findings from `reports/external/live-payments-audit-2026-04-05-combined.md`
* C1-C4, H1-H3, M1-M5

## Plan and do the implementation

## Completed

**Date:** 2026-04-05
**PRs:** #57 (merged), #58 (pending)

### Addressed in PR #57 (merged)
- **C1** — Stripe live/test key boot assertion (refuses to start with `sk_live_*` in non-prod)
- **C2** — Capture atomicity (CAS state transition + compensation on failure)
- **C3** — Double-capture 409 (uniqueness enforced on status transition)
- **C4** — Refund balance restoration (reverse ledger on settled refund)
- **H1** — Overdraft withdraw returns 402 instead of 500
- **H3** — Gateway fee disclosed in `create_intent` response
- **M1** — Deposit returns `transaction_id` in response
- **M2** — Transaction field aliases (`type`/`timestamp`)
- **M3** — `AgentIdLengthMiddleware` returns typed 400 URI

### Addressed in PR #58 (this branch)
- **H2** — `HttpsEnforcementMiddleware`: 308 redirect on safe methods,
  400 reject on mutating methods when `X-Forwarded-Proto: http` and
  `FORCE_HTTPS=1`. 12 tests in `test_https_enforcement.py`.
- **H3 follow-up** — `refund_intent` now reverses the `create_intent` gateway
  fee on void/refund, credited to the payer. Response body includes
  `gateway_fee` field. 7 tests in `test_refund_gateway_fee.py`.
- **M4/M5** — ADR-010 documents 403-before-404 (BOLA-prevention) and
  `/v1/identity/metrics` path semantics.
- **Docs** — `api-reference.md` updated with gateway fee disclosure and
  refund-reversal behavior.
