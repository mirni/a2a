# ADR-011: Refund Fee Policy (Retain Gateway Fee on Refund)

**Status:** Accepted
**Date:** 2026-04-10
**Context:** Multi-persona audit v1.2.2 (HIGH-2)

## Context

When a caller refunds a settled payment intent, two outcomes are possible
for the 2 % gateway fee that was charged at `create_intent` time:

1. **Retain** — the principal (payment amount) is returned to the payer
   but the 2 % gateway fee is kept by the platform. Net result: the payer
   is down by `2 % × amount` after a full refund.
2. **Refund** — both principal and gateway fee are returned to the payer.
   Net result: the payer is whole, and the platform absorbs the 2 % it
   already debited.

The v1.2.1 audit (HIGH-2) made the behavior transparent via
`fee_refunded: false` and `fee_retained: "1.00"` on the refund response.
The v1.2.2 audit escalated the finding: transparency alone is not enough —
integrators need a **stable, citeable policy URL** so their own
reconciliation docs can link to it, and the platform needs a recorded
decision so future maintainers don't flip the default during a refactor.

## Decision

**The gateway retains the 2 % gateway fee on refund.**

### Rationale

1. **Execution cost is already incurred.** The gateway fee pays for
   fraud checks, idempotency storage, ledger writes, and signed receipt
   generation. These resources are consumed at `create_intent` /
   `capture` time regardless of whether the payment is later refunded.
   Refunding the fee would mean the platform pays to process a payment
   that produces zero revenue.

2. **Industry standard for card-not-present.** Stripe, Adyen, and
   Braintree all retain processing fees on refund for the same reason.
   Integrators moving from those processors already expect this
   behavior and budget around it.

3. **Discourages refund-based fee arbitrage.** If the gateway fee were
   refunded, a caller could create and immediately refund high-value
   intents to mint free gateway events (useful for metric-inflation
   attacks on reputation systems).

4. **Simple to document.** A single flat rule is easier to explain to
   auditors than a tiered refund schedule.

### Response shape

Every refund response — across both `voided`, `refunded`, and the
idempotent-replay path — carries a `fee_policy` object:

```json
{
  "id": "intent_abc",
  "status": "refunded",
  "amount": "50.00",
  "gateway_fee": "1.00",
  "fee_refunded": false,
  "fee_retained": "1.00",
  "fee_policy": {
    "name": "retain_gateway_fee",
    "adr": "ADR-011",
    "url": "https://docs.greenhelix.net/adr/011-refund-fee-policy",
    "summary": "The 2% gateway fee is retained on refund. See ADR-011."
  }
}
```

`fee_refunded` / `fee_retained` remain in place for backwards
compatibility with v1.2.1 integrators.

## Alternatives considered

* **Refund everything (Option B in the audit response).** Rejected for
  the reasons above. Would require reconciliation work on the gateway's
  own ledger and a ledger-adjustment entry for every refund.
* **Tiered refund (refund fee only on payee-initiated refunds).**
  Rejected as too complex to explain. A tiered schedule also creates a
  chargeback-arbitrage loophole where a payer disputes with the payee
  instead of using the payer-initiated refund flow.

## Consequences

* Integrators must reconcile against `fee_retained` on every refund.
  The response now cites ADR-011, so their finance team can link to the
  rationale.
* Any future change to the default (e.g. a paid "refund insurance"
  tier) must be recorded as a new ADR that supersedes this one.
* The `fee_policy.name` field is a stable identifier; clients can
  branch on it once alternative policies are introduced.

## References

* `gateway/src/tools/payments.py::_refund_intent` — response construction
* `gateway/tests/v1/test_audit_v1_2_2_regressions.py::TestRefundFeePolicyDisclosure`
* Audit report: `reports/external/v1.2.2/multi-persona-audit-v1.2.2-2026-04-10.md` (HIGH-2)
