# ADR-002: SQLite-per-Product Database Architecture

**Date:** 2026-03-28
**Status:** Accepted
**Role:** Architect

## Context

The platform consists of ~10 loosely-coupled products (billing, payments,
identity, marketplace, trust, messaging, paywall, disputes, event_bus,
webhooks). Each has its own storage needs, retention policy, and schema
evolution cadence. We need a database strategy that:

- Lets products be developed and tested in isolation
- Has low operational overhead for a small team
- Supports ACID transactions within each product's bounded context
- Can run on a single VPS (< $50/month hosting) at MVP scale
- Avoids premature introduction of a distributed system

## Decision

**Each product owns its own SQLite database file** under
`/var/lib/a2a/<product>.db`. Products interact only via their public
Python APIs or over the gateway's HTTP layer — never by reading each
other's databases.

| Product | DB file |
| --- | --- |
| billing | `billing.db` |
| payments | `payments.db` |
| identity | `identity.db` |
| paywall | `paywall.db` |
| marketplace | `marketplace.db` |
| trust | `trust.db` |
| messaging | `messaging.db` |
| disputes | `disputes.db` |
| event_bus | `event_bus.db` (24h rolling) |
| webhooks | `webhooks.db` |

Schemas are declared in each product's `storage.py` `_SCHEMA` block and
versioned via `PRAGMA user_version`. Migrations are applied only through
`scripts/migrate_db.sh`.

## Alternatives Considered

- **Single PostgreSQL DB, one schema per product.** More ops overhead
  (backup, HA, tuning), requires a Postgres server. Doesn't scale to
  zero on dev laptops. Rejected for MVP; will revisit past 10K req/s.
- **Single SQLite DB for all products.** Simpler backups, but couples
  schema evolution, locks, and retention across products. Rejected.
- **One DB per tenant.** Required only if we pursue strict tenant
  isolation. Premature now.

## Consequences

### Positive

- Clear ownership boundaries → easier parallel development
- Products can be VACUUMed, backed up, and migrated independently
- Full schema fits in git; reproducible in CI without infra
- SQLite WAL mode gives us concurrent reads + single-writer semantics
  which matches our workload (read-heavy lookups, serialized writes)

### Negative

- **No cross-DB atomic transactions.** Cross-product operations (e.g.
  payments capture → billing debit) must use the compensation pattern
  (see `products/payments/src/engine.py::capture`).
- Joins across products happen in Python, not SQL
- Scaling past a single host requires migrating each DB to Postgres
  (work is localized per product but still non-trivial)

### Mitigations

- Compensation paths are covered by explicit tests (see
  `test_capture_deposit_failure_preserves_payer_balance`)
- Critical invariants (wallet balance conservation, no negative balances)
  are verified by post-recovery checks in `db-recovery.md`
- Postgres migration path is documented per-product (future work)

## Related

- ADR-006: Decimal money handling
- [db-recovery.md](../infra/runbooks/db-recovery.md)
