# ADR-003: FastAPI Gateway as Single Public Entrypoint

**Date:** 2026-03-28
**Status:** Accepted
**Role:** Architect

## Context

Customers (AI agents) need a single HTTP entrypoint that unifies ~128
tools across 10+ products, handles authentication, rate limiting,
billing, and request/response validation. The gateway must:

- Run on vanilla Python with minimal dependencies
- Support async I/O (outbound calls to Stripe, webhooks, connectors)
- Emit OpenAPI for SDK generation
- Enforce per-tier rate limits, per-tool billing, and tenant isolation
- Be deployable as a single systemd service on a Debian host

## Decision

**One FastAPI application (`gateway/src/app.py`) serves all public
traffic** on a single port (8000 in dev, 443 behind Cloudflare in prod).
Uvicorn is the ASGI server. The gateway imports each product directly
(no service mesh).

Structure:

```
gateway/src/
├── app.py              # create_app() — wires routers + middleware
├── lifespan.py         # startup/shutdown hooks (DB init, boot assertions)
├── routes/
│   ├── v1/
│   │   ├── billing.py
│   │   ├── payments.py
│   │   ├── identity.py
│   │   └── ...
│   ├── pricing.py
│   ├── health.py
│   └── agent_card.py
├── deps/               # shared dependencies: auth, billing, rate_limit
├── middleware/         # error, cors, request_id, agent_id_length
├── errors.py           # RFC 9457 problem details
└── catalog.py          # tool registry + pricing
```

## Alternatives Considered

- **Multiple services** (payments-svc, billing-svc, etc.) behind an
  API gateway like Kong/Envoy. Too much infra for single-host MVP;
  introduces network hops for cross-product ops.
- **Flask + sync workers.** Loses async support needed for outbound
  Stripe calls and the execute endpoint's sub-50ms budget.
- **AWS API Gateway + Lambda.** Vendor lock-in, cold-start latency,
  harder local dev.

## Consequences

### Positive

- Single process → single logs, single backups, single deploy artifact
- In-process calls to products are µs latency (no RPC)
- FastAPI's Pydantic integration gives us validation + OpenAPI for free
- Hot-reload via `systemctl reload` (SIGHUP, 30s drain)

### Negative

- Monolith blast radius: a buggy tool can crash the whole gateway
- Cannot scale tools independently (all or nothing workers)
- Global Python GIL bounds throughput to ~1 worker-per-core

### Mitigations

- Per-tool timeouts + circuit-breakers (future work)
- Uvicorn multi-worker mode once single-worker saturates
- When we outgrow a single VPS, split at product boundaries (each
  product is already self-contained — see ADR-002)

## Related

- ADR-002: SQLite-per-product
- ADR-007: Pydantic request validation
- ADR-009: Authentication + rate limiting
- [gateway-restart.md](../infra/runbooks/gateway-restart.md)
