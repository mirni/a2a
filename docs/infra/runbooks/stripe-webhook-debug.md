# Stripe Webhook Debug Runbook

**Purpose:** Diagnose and fix Stripe webhook delivery failures — signature
verification errors, duplicate delivery, missing callbacks, or bad data.

**Audience:** On-call engineer, payments developer.

**Pre-conditions:** Stripe Dashboard access + SSH on gateway host.

---

## 1. Symptoms

| Symptom | Likely cause | Jump to |
| --- | --- | --- |
| Stripe Dashboard shows "Failed" webhook attempts | Signature mismatch or 5xx from gateway | §3 |
| Customer paid but credits never appeared | Webhook never arrived, or processed twice and silently deduped | §4 |
| `stripe_webhook_dedup` error in logs | DB unavailable during webhook | §5 |
| Multiple credit entries for single Stripe session | Missing dedup or replayed webhook | §6 |
| 401 from gateway on webhook POST | Stripe secret mismatch | §3 |

---

## 2. Health check (do this first)

```bash
# 1. Recent webhook activity on our side
ssh a2a-prod
sudo journalctl -u a2a-gateway --since "1 hour ago" | \
    grep -i -E "webhook|stripe" | tail -50

# 2. Stripe's delivery log
# Dashboard → Developers → Webhooks → select endpoint → "Attempts" tab
# Look for: 2xx vs 4xx/5xx distribution, retry counts

# 3. Our Stripe session rows
sqlite3 /var/lib/a2a/billing.db \
    "SELECT session_id, status, created_at, processed_at
     FROM stripe_sessions ORDER BY created_at DESC LIMIT 10;"
```

---

## 3. Signature verification failures

**Symptom:** gateway logs show `SignatureVerificationError` or Dashboard
shows 400 responses from our endpoint.

```bash
# 1. Verify the webhook signing secret matches
# Stripe Dashboard → Developers → Webhooks → endpoint → "Signing secret" → Reveal

# 2. Compare to our config
sudo cat /etc/a2a-gateway/gateway.env | grep STRIPE_WEBHOOK_SECRET
# Must match Stripe's `whsec_*` value exactly

# 3. If mismatched, update env and reload
sudo systemctl reload a2a-gateway

# 4. Ask Stripe to resend the failed event
# Dashboard → Webhook attempt → "Resend"
```

**Audit C1:** verify STRIPE_API_KEY matches A2A_ENV (sandbox must use
`sk_test_*`, prod must use `sk_live_*`). Boot assertion enforces this —
mismatches will log `REFUSING TO BOOT`.

---

## 4. Missing webhook (customer paid, no credits)

```bash
# 1. Get the Stripe session ID from the customer
# (Format: cs_live_xxx or cs_test_xxx)

# 2. Check if we have it
sqlite3 /var/lib/a2a/billing.db \
    "SELECT * FROM stripe_sessions WHERE session_id = 'cs_live_...';"

# 3. If missing: the webhook never arrived.
#    Check Stripe Dashboard → Events → filter by session ID.
#    - If event exists: gateway was offline when webhook fired.
#      Ask Stripe to resend from Dashboard.
#    - If event missing: customer completed checkout but event wasn't
#      generated. Contact Stripe support.

# 4. Manual credit (if Stripe confirms payment but resend fails):
# Verify the payment on Stripe side first, then:
curl -fsS -X POST "https://api.stripe.com/v1/checkout/sessions/cs_live_.../" \
    -u $STRIPE_API_KEY: | jq '{id, amount_total, payment_status, customer_email}'

# Then issue credits via admin tool (requires admin API key):
curl -fsS -X POST https://api.greenhelix.net/v1/billing/wallets/<agent-id>/deposit \
    -H "Authorization: Bearer $ADMIN_KEY" \
    -H "Idempotency-Key: manual-cs_live_..." \
    -d '{"amount": 100.0, "description": "manual credit — Stripe cs_live_..."}'
```

Document the manual credit in `docs/infra/incidents/YYYY-MM-DD.md`.

---

## 5. DB unavailable during webhook

**Symptom:** gateway returns 503 to Stripe, webhook retries at exponential
backoff (Stripe retries for up to 3 days).

```bash
# 1. Check DB health
sqlite3 /var/lib/a2a/billing.db "PRAGMA integrity_check;" | head -3

# 2. Check for lock
sudo lsof /var/lib/a2a/billing.db | grep -v gateway

# 3. If the gateway itself is holding a lock, restart (see
#    gateway-restart.md)
sudo systemctl reload a2a-gateway

# 4. Check Stripe delivery state after recovery
# Dashboard → Developers → Webhooks → endpoint → Attempts → "Resend"
# — or wait: Stripe will retry automatically.
```

---

## 6. Duplicate delivery

Stripe guarantees **at-least-once** delivery. We dedupe on
`stripe_sessions.session_id` (unique index) — idempotent on our side.

**Symptom:** two credit transactions with the same session ID.

```bash
# 1. Confirm duplicates exist
sqlite3 /var/lib/a2a/billing.db \
    "SELECT session_id, COUNT(*) FROM stripe_sessions GROUP BY session_id HAVING COUNT(*) > 1;"

# 2. If duplicates exist, this is a DB-schema bug.
#    Audit the dedup code path (gateway/src/stripe_checkout.py).
#    Check if the unique index is present:
sqlite3 /var/lib/a2a/billing.db \
    ".schema stripe_sessions" | grep -i unique

# 3. Reverse the duplicate (requires human approval):
# Identify the doubled transaction via transactions table
sqlite3 /var/lib/a2a/billing.db \
    "SELECT * FROM transactions WHERE description LIKE '%cs_live_...%';"

# Adjust manually via an admin-audited correction transaction.
```

---

## 7. Test webhook locally

```bash
# Stripe CLI (install: https://stripe.com/docs/stripe-cli)
stripe listen --forward-to http://localhost:8000/v1/webhooks/stripe

# In another terminal, trigger:
stripe trigger checkout.session.completed
```

The CLI prints the local webhook secret — set it temporarily in
`gateway.env` for local testing (never commit).

---

## 8. Escalation

- Signature mismatch > 15 min: escalate to CTO
- Missing credits > 5 customers: escalate to CFO
- Stripe-side outage: check status.stripe.com before escalating

---

*Last reviewed: 2026-04-05. Owner: CTO + Payments lead. Review cadence: quarterly.*
