# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) documenting
the significant technical decisions made on the A2A Commerce Platform.

Each ADR captures **context**, **decision**, **alternatives**, and
**consequences** so future contributors understand *why* the system
looks the way it does.

## Index

| # | Title | Status | Date |
| --- | --- | --- | --- |
| 001 | [Technology Stack](001-tech-stack.md) | Accepted | 2026-03-26 |
| 002 | [SQLite-per-Product Database Architecture](002-sqlite-per-product.md) | Accepted | 2026-03-28 |
| 003 | [FastAPI Gateway as Single Public Entrypoint](003-fastapi-gateway.md) | Accepted | 2026-03-28 |
| 004 | [RFC 9457 Problem Details for HTTP Errors](004-rfc9457-errors.md) | Accepted | 2026-03-30 |
| 005 | [Idempotency Keys for Mutating Endpoints](005-idempotency-keys.md) | Accepted | 2026-03-30 |
| 006 | [Decimal Arithmetic for All Monetary Values](006-decimal-money.md) | Accepted | 2026-03-30 |
| 007 | [Pydantic Request Validation with `extra = "forbid"`](007-pydantic-validation.md) | Accepted | 2026-03-30 |
| 008 | [Capture Atomicity via Compare-and-Set + Compensation](008-capture-atomicity.md) | Accepted | 2026-04-05 |
| 009 | [Authentication and Rate Limiting Architecture](009-auth-rate-limiting.md) | Accepted | 2026-03-30 |

## Writing a new ADR

1. Copy the format of an existing ADR (004 is a good template for small
   decisions; 008 is a good template for large ones).
2. Name it `NNN-short-kebab-title.md` with the next available number.
3. Fill in: Context, Decision, Alternatives Considered, Consequences
   (Positive / Negative / Mitigations), Related.
4. Open a PR — ADRs are peer-reviewed like code.
5. Once merged, status is `Accepted`. Never edit the decision section
   of an accepted ADR; write a new ADR superseding it instead.

## Status values

- **Proposed** — draft, under review
- **Accepted** — decision made and implemented
- **Deprecated** — still in use but not recommended for new code
- **Superseded by ADR-NNN** — replaced by a newer decision
