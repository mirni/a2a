# API Design Review: Richardson Maturity Model Assessment

**Date:** 2026-03-31 (updated)
**Reviewer Role:** Sr. Software Architect
**Scope:** Full A2A Commerce Gateway API surface (125+ tools, 15 services)
**Framework:** FastAPI (migrated from Starlette)

---

## Executive Summary

The A2A Commerce Gateway is a **Level 1** API with **partial Level 2** compliance. It uses a single-endpoint RPC pattern (`POST /v1/execute`) to dispatch 125+ tools, which is architecturally closer to JSON-RPC than REST. While this "universal gateway" pattern has operational simplicity, it sacrifices HTTP semantics, cacheability, and discoverability — all of which matter for a public-facing commerce API.

The gateway was recently migrated to **FastAPI**, which gives us auto-generated OpenAPI docs, Swagger UI at `/docs`, and native Pydantic validation. This makes the RESTful refactor significantly simpler — FastAPI's `APIRouter` system is purpose-built for resource-oriented routing.

**There are no current API clients.** Breaking changes are acceptable. The goal is to reach **HATEOAS (Level 3)** directly, without a gradual migration.

---

## 1. Current State: Richardson Maturity Model Assessment

### Level 0 — The Swamp of POX

**Status: PASSED (the API is above Level 0)**

The API is not a single-endpoint XML/SOAP service. It uses JSON, HTTP status codes, and has multiple endpoints.

### Level 1 — Resources

**Status: PARTIAL**

| Criterion | Current State | Gap |
|-----------|--------------|-----|
| Distinct URIs for resources | `/v1/execute` handles everything | Billing, payments, marketplace, etc. share one endpoint |
| Resource identity in URLs | Tool name is a body param, not a URI segment | `POST /v1/execute {"tool": "get_balance"}` vs `GET /v1/billing/wallets/{id}/balance` |
| Nouns, not verbs | Tool names are verbs: `create_intent`, `deposit`, `withdraw` | URLs should represent resources (wallets, intents, escrows) |
| Resource-oriented responses | Results are tool-specific dicts inside `{"success": true, "result": {...}}` | No self-describing resource representations |

**Exceptions (already at Level 1+):**
- `GET /v1/pricing` — proper resource collection
- `GET /v1/pricing/{tool}` — proper resource instance
- `GET /v1/health` — proper resource
- `GET /v1/events/stream` — proper SSE resource

### Level 2 — HTTP Verbs

**Status: PARTIAL**

| Criterion | Current State | Gap |
|-----------|--------------|-----|
| GET for reads | `get_balance` is `POST /v1/execute` | Should be `GET /v1/billing/wallets/{id}` |
| POST for creates | `create_intent` is `POST /v1/execute` | Should be `POST /v1/payments/intents` |
| PUT/PATCH for updates | `update_service` is `POST /v1/execute` | Should be `PATCH /v1/marketplace/services/{id}` |
| DELETE for deletes | `delete_server` is `POST /v1/execute` | Should be `DELETE /v1/trust/servers/{id}` |
| Proper status codes | Good: 200, 400, 401, 402, 403, 404, 409, 422, 429, 503 | Missing: 201 Created, 204 No Content, 304 Not Modified |
| Cacheability | All reads go through POST (uncacheable) | GET responses can use ETag/Last-Modified |
| Idempotency | Supported via `idempotency_key` param | Should also use `Idempotency-Key` header (IETF standard) |
| Content negotiation | JSON only, no Accept header handling | Should support `Accept: application/json` explicitly |

**What already works well:**
- Rate limit headers (`X-RateLimit-Limit/Remaining/Reset`) -- correct pattern
- Correlation IDs (`X-Request-ID`) -- correct pattern
- Security headers (HSTS, CSP, X-Frame-Options) -- correct pattern
- Error response structure (`{success, error: {code, message}}`) -- consistent
- `extra = "forbid"` on all Pydantic request models -- strict validation
- FastAPI auto-generates OpenAPI spec at `/v1/openapi.json` and Swagger UI at `/docs`

### Level 3 — Hypermedia Controls (HATEOAS)

**Status: NOT IMPLEMENTED**

| Criterion | Current State | Gap |
|-----------|--------------|-----|
| Links in responses | No `_links` or `Link` headers | Clients must hardcode URIs |
| State transitions | Not communicated in responses | E.g., intent response should include links to `capture`, `void`, `refund` |
| Pagination links | `offset`/`limit` in response body, no `next`/`prev` URLs | Should include `Link: <url>; rel="next"` |
| Self-links | No `self` link in any response | Every resource should have a `self` URL |
| Discoverability | `/v1/pricing` lists tools but no navigation links | Should link to individual tool endpoints |
| Media types | No custom media type | Could use `application/vnd.a2a.v1+json` for versioning |

---

## 2. Detailed Design Issues

### 2.1 The Single-Endpoint Anti-Pattern

The `POST /v1/execute` endpoint is a **procedure dispatcher**, not a REST endpoint:

```
POST /v1/execute {"tool": "get_balance", "params": {"agent_id": "x"}}
POST /v1/execute {"tool": "create_intent", "params": {"payer": "a", "payee": "b", "amount": 100}}
POST /v1/execute {"tool": "refund_intent", "params": {"intent_id": "abc"}}
```

**Problems:**
1. **No cacheability** — GET requests for read-only data (balances, listings, scores) cannot be cached by HTTP intermediaries (CDNs, reverse proxies, browsers).
2. **No bookmarkability** — There's no URL to reference a specific intent, wallet, or service.
3. **No HTTP-level observability** — All requests look identical in access logs (`POST /v1/execute 200`). You can't distinguish a balance check from a payment without parsing the body.
4. **No conditional requests** — Cannot use `If-None-Match`/`If-Modified-Since` for bandwidth optimization.
5. **No HTTP-level authorization** — Reverse proxies/API gateways can't apply path-based ACLs.

### 2.2 Inconsistent Response Envelope

Current responses wrap everything in `{success, result, charged, request_id}`:

```json
{
  "success": true,
  "result": {"balance": 500.0, "currency": "CREDITS"},
  "charged": 0.01,
  "request_id": "uuid"
}
```

**Problems:**
1. The `result` field is untyped — its schema depends entirely on which tool was called.
2. `charged` and `request_id` are billing/observability metadata, not the resource itself. These belong in response headers.
3. The `success: true/false` boolean is redundant with HTTP status codes.
4. Clients need special envelope-unwrapping logic for every response.

### 2.3 Missing Standard Pagination

Current pagination on `/v1/pricing`:
```json
{"tools": [...], "total": 125, "limit": 5, "offset": 0}
```

**Problems:**
1. No `next`/`prev` links — clients must construct URLs manually.
2. No `Link` header — standard for RESTful pagination.
3. Offset-based pagination is fragile under concurrent writes (items can be skipped or duplicated).

### 2.4 Missing Standard Error Format

Current error format:
```json
{"success": false, "error": {"code": "missing_key", "message": "Missing API key"}}
```

This is custom. Should adopt **RFC 9457 (Problem Details for HTTP APIs)**:
```json
{
  "type": "https://api.greenhelix.net/errors/missing-key",
  "title": "Missing API Key",
  "status": 401,
  "detail": "No API key was provided in the Authorization header.",
  "instance": "/v1/billing/wallets/agent-123"
}
```

### 2.5 Batch Endpoint Design

Current: `POST /v1/batch {"calls": [{"tool": "...", "params": {...}}, ...]}`

This is JSON-RPC batching. In a RESTful design, batching is less necessary because each resource has its own endpoint, and clients can use HTTP/2 multiplexing for parallel requests. **Remove after resource endpoints exist.**

### 2.6 Versioning

Current: URL path prefix `/v1/`. This is acceptable and widely used. The backward-compatibility redirects can be removed (no clients to break).

### 2.7 Missing Standard Headers

| Header | Purpose | Current Status |
|--------|---------|----------------|
| `Idempotency-Key` | IETF standard for idempotent POST | Using body param `idempotency_key` instead |
| `Retry-After` | Indicate when to retry after 429 | Partially implemented |
| `ETag` / `Last-Modified` | Conditional GET | Not implemented |
| `Link` | Pagination, related resources | Not implemented |
| `Location` | Created resource URI (201) | Not implemented |

---

## 3. Proposed RESTful Resource Model (Level 2)

### 3.1 Resource Hierarchy

Each service gets its own `APIRouter` in FastAPI. Route registration is automatic.

```
/v1/billing/
    /wallets                          GET (list), POST (create)
    /wallets/{agent_id}               GET (balance + details)
    /wallets/{agent_id}/transactions  GET (ledger history)
    /wallets/{agent_id}/budget        GET, PUT (budget caps)
    /wallets/{agent_id}/usage         GET (usage summary)
    /exchange-rates/{from}/{to}       GET
    /analytics/leaderboard            GET
    /analytics/revenue                GET

/v1/payments/
    /intents                          GET (list), POST (create)
    /intents/{id}                     GET
    /intents/{id}/capture             POST (action)
    /intents/{id}/void                POST (action)
    /intents/{id}/refund              POST (action)
    /escrows                          GET (list), POST (create)
    /escrows/{id}                     GET
    /escrows/{id}/release             POST (action)
    /escrows/{id}/cancel              POST (action)
    /settlements/{id}                 GET
    /settlements/{id}/refund          POST (action)
    /subscriptions                    GET (list), POST (create)
    /subscriptions/{id}               GET, DELETE (cancel)
    /subscriptions/{id}/reactivate    POST (action)

/v1/marketplace/
    /services                         GET (search), POST (register)
    /services/{id}                    GET, PATCH, DELETE
    /services/{id}/ratings            GET, POST
    /agents                           GET (search)
    /match                            POST (best-match query)

/v1/trust/
    /servers                          GET (list), POST (register)
    /servers/{id}                     GET, PATCH, DELETE
    /servers/{id}/score               GET (trust score)
    /servers/{id}/health              GET (probe results)

/v1/identity/
    /agents                           POST (register)
    /agents/{id}                      GET
    /agents/{id}/keys                 GET, POST (rotate)
    /agents/{id}/metrics              GET, POST (submit)
    /agents/{id}/claims               GET
    /agents/{id}/reputation           GET
    /orgs                             GET (list), POST (create)
    /orgs/{id}                        GET
    /orgs/{id}/members                GET, POST, DELETE

/v1/messaging/
    /messages                         GET (inbox), POST (send)
    /threads/{id}                     GET
    /negotiations                     POST (initiate)

/v1/events/
    /stream                           GET (SSE) — already exists
    /schemas                          GET (list), POST (register)
    /schemas/{type}                   GET

/v1/webhooks/
    /                                 GET (list), POST (register)
    /{id}                             GET, DELETE
    /{id}/deliveries                  GET
    /{id}/test                        POST

/v1/disputes/
    /                                 GET (list), POST (open)
    /{id}                             GET
    /{id}/respond                     POST
    /{id}/resolve                     POST (admin)

/v1/connectors/
    /stripe/*                         Proxy to Stripe MCP
    /github/*                         Proxy to GitHub MCP
    /postgres/*                       Proxy to PostgreSQL MCP
```

### 3.2 Response Format (No Envelope)

**Resource response:**
```json
GET /v1/billing/wallets/agent-123

200 OK
X-Request-ID: uuid-123
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 987

{
  "agent_id": "agent-123",
  "balance": "500.00",
  "currency": "CREDITS",
  "frozen": false,
  "created_at": "2026-03-15T10:00:00Z"
}
```

**Created resource:**
```json
POST /v1/payments/intents
Idempotency-Key: txn-abc-123

201 Created
Location: /v1/payments/intents/intent-456
X-Request-ID: uuid-789
X-Charged: 0.25

{
  "id": "intent-456",
  "payer": "agent-1",
  "payee": "agent-2",
  "amount": "100.00",
  "status": "pending",
  "created_at": "2026-03-31T12:00:00Z"
}
```

**Error response (RFC 9457):**
```json
402 Payment Required

{
  "type": "https://api.greenhelix.net/errors/insufficient-balance",
  "title": "Insufficient Balance",
  "status": 402,
  "detail": "Wallet balance 50.00 is less than required 100.00 credits.",
  "instance": "/v1/payments/intents"
}
```

**Paginated collection:**
```json
GET /v1/billing/wallets/agent-123/transactions?limit=10&cursor=txn-500

200 OK
Link: </v1/billing/wallets/agent-123/transactions?limit=10&cursor=txn-490>; rel="next"

{
  "data": [...],
  "pagination": {
    "total": 1523,
    "limit": 10,
    "has_more": true,
    "next_cursor": "txn-490"
  }
}
```

### 3.3 Billing Metadata in Headers

Move billing/observability data out of the response body into headers:

| Header | Purpose |
|--------|---------|
| `X-Request-ID` | Correlation ID (already implemented) |
| `X-Charged` | Credits charged for this request |
| `X-Balance-Remaining` | Post-request wallet balance |
| `X-RateLimit-*` | Rate limit info (already implemented) |

---

## 4. HATEOAS Design (Level 3)

### 4.1 Hypermedia Links in Responses

**Payment intent with state transitions:**
```json
GET /v1/payments/intents/intent-456

{
  "id": "intent-456",
  "status": "pending",
  "amount": "100.00",
  "payer": "agent-1",
  "payee": "agent-2",
  "_links": {
    "self": {"href": "/v1/payments/intents/intent-456"},
    "capture": {"href": "/v1/payments/intents/intent-456/capture", "method": "POST"},
    "void": {"href": "/v1/payments/intents/intent-456/void", "method": "POST"},
    "payer_wallet": {"href": "/v1/billing/wallets/agent-1"},
    "payee_wallet": {"href": "/v1/billing/wallets/agent-2"}
  }
}
```

After capture (`status: "settled"`), links change:
```json
{
  "id": "intent-456",
  "status": "settled",
  "_links": {
    "self": {"href": "/v1/payments/intents/intent-456"},
    "refund": {"href": "/v1/payments/intents/intent-456/refund", "method": "POST"},
    "settlement": {"href": "/v1/payments/settlements/settle-789"}
  }
}
```

### 4.2 Collection Links

```json
GET /v1/marketplace/services?category=trading&limit=5

{
  "data": [...],
  "_links": {
    "self": {"href": "/v1/marketplace/services?category=trading&limit=5&offset=0"},
    "next": {"href": "/v1/marketplace/services?category=trading&limit=5&offset=5"},
    "search": {"href": "/v1/marketplace/services{?query,category,tags,max_cost}", "templated": true}
  }
}
```

### 4.3 API Entry Point

```json
GET /v1/

{
  "version": "0.4.9",
  "_links": {
    "billing": {"href": "/v1/billing/wallets"},
    "payments": {"href": "/v1/payments/intents"},
    "marketplace": {"href": "/v1/marketplace/services"},
    "trust": {"href": "/v1/trust/servers"},
    "identity": {"href": "/v1/identity/agents"},
    "messaging": {"href": "/v1/messaging/messages"},
    "events": {"href": "/v1/events/stream"},
    "webhooks": {"href": "/v1/webhooks"},
    "disputes": {"href": "/v1/disputes"},
    "health": {"href": "/v1/health"},
    "docs": {"href": "/docs"},
    "openapi": {"href": "/v1/openapi.json"}
  }
}
```

---

## 5. Additional Design Recommendations

### 5.1 Adopt RFC 9457 (Problem Details)

Replace the custom `{success, error: {code, message}}` format with the standard:

```python
class ProblemDetail(BaseModel):
    type: str         # URI reference to error documentation
    title: str        # Short, human-readable summary
    status: int       # HTTP status code
    detail: str       # Human-readable explanation specific to this occurrence
    instance: str     # URI of the request that caused the error
```

FastAPI's exception handlers can return `application/problem+json` natively.

### 5.2 Adopt Cursor-Based Pagination

Replace offset-based pagination with cursor-based for consistency under concurrent writes:

```
GET /v1/billing/wallets/agent-1/transactions?limit=10&cursor=eyJ0cyI6MTcxMTg3NjQ5Nn0
```

Cursor is an opaque base64-encoded token (e.g., `{"ts": 1711876496, "id": 500}`).

### 5.3 Adopt `Idempotency-Key` Header

Per the IETF draft (widely adopted by Stripe, PayPal, etc.):

```
POST /v1/payments/intents
Idempotency-Key: txn-abc-123
```

Replace the current body parameter `idempotency_key`.

### 5.4 Use ISO 8601 Timestamps

Replace Unix epoch floats with ISO 8601 strings in all responses:

```json
// Current
{"created_at": 1711876496.123}

// Target
{"created_at": "2026-03-31T12:34:56.123Z"}
```

### 5.5 Use Consistent Decimal Serialization

All monetary amounts should serialize as strings to preserve precision:

```json
// Current (float)
{"balance": 500.0, "charged": 0.01}

// Target (string)
{"balance": "500.00", "charged": "0.01"}
```

### 5.6 ETags for Conditional GETs

For frequently-polled resources (balance, trust score, service listings):

```
GET /v1/billing/wallets/agent-123
-> ETag: "abc123"

GET /v1/billing/wallets/agent-123
If-None-Match: "abc123"
-> 304 Not Modified (no body, saves bandwidth)
```

### 5.7 OpenAPI Spec

FastAPI auto-generates the OpenAPI spec from route definitions and Pydantic models. After refactoring:
- Each resource endpoint is automatically documented
- `_links` fields appear in response schemas via Pydantic models
- Shared models (`ProblemDetail`, `PaginatedResponse`, etc.) use `$ref` automatically
- The custom `openapi.py` merge logic can be simplified since routes are now self-documenting

---

## 6. Implementation Plan

Since there are no existing clients, we can refactor directly without maintaining backward compatibility or migration phases.

### Phase 1: Foundation

1. **Remove response envelope** — Return resources directly. Move `charged`, `request_id` to headers (`X-Charged`, `X-Request-ID`).
2. **Adopt RFC 9457 errors** — Replace `{success: false, error: {code, message}}` with `application/problem+json`.
3. **Adopt `Idempotency-Key` header** — Replace body parameter.
4. **Adopt ISO 8601 timestamps** and **string-serialized Decimals** across all models.
5. **Add `201 Created` + `Location` header** for POST endpoints that create resources.
6. **Add cursor-based pagination** with `Link` header.

### Phase 2: Resource Endpoints

1. **Create `APIRouter` per service** — `billing_router`, `payments_router`, `marketplace_router`, etc.
2. **Map each tool to a resource endpoint** — e.g., `get_balance` -> `GET /v1/billing/wallets/{agent_id}`, `create_intent` -> `POST /v1/payments/intents`.
3. **Use proper HTTP methods** — GET for reads, POST for creates, PATCH for updates, DELETE for deletes.
4. **Remove `/v1/execute`** — All functionality is now on resource endpoints.
5. **Remove `/v1/batch`** — HTTP/2 multiplexing replaces it.
6. **Remove backward-compatibility redirects** — No clients to redirect.

### Phase 3: HATEOAS

1. **Add `_links`** to all resource responses with `self`, state transitions, and related resources.
2. **Add `Link` header** for pagination (`rel="next"`, `rel="prev"`).
3. **Add `GET /v1/`** API root with service index and links.
4. **Add link templates** for search endpoints (`{?query,category,limit}`).
5. **Add `ETag` / `If-None-Match`** support for read endpoints.
6. **Add `Vary: Authorization`** header to enable CDN caching of public endpoints.

---

## 7. Actionable TODO List

### Priority 0 (Foundation)

- [ ] **T1:** Create ADR `docs/adr/002-restful-resource-model.md` documenting the decision to move from RPC to REST
- [ ] **T2:** Define the full resource URL hierarchy in a new PRD `docs/prd/015-rest-api-refactor.md`
- [ ] **T3:** Replace response envelope with direct resource responses; move `charged` to `X-Charged` header
- [ ] **T4:** Adopt RFC 9457 (Problem Details) error format; add FastAPI exception handlers returning `application/problem+json`
- [ ] **T5:** Adopt `Idempotency-Key` request header (replace body parameter)
- [ ] **T6:** Add `201 Created` + `Location` header for POST endpoints that create resources
- [ ] **T7:** Serialize all monetary values as strings in JSON responses (Decimal precision)
- [ ] **T8:** Serialize all timestamps as ISO 8601 strings in responses
- [ ] **T9:** Add cursor-based pagination with `Link` header to all list endpoints

### Priority 1 (Resource Endpoints)

- [ ] **T10:** Create `APIRouter` for billing: `GET /v1/billing/wallets/{agent_id}`, `GET .../transactions`, etc.
- [ ] **T11:** Create `APIRouter` for payments: `POST /v1/payments/intents`, `GET .../intents/{id}`, action sub-resources (capture, void, refund)
- [ ] **T12:** Create `APIRouter` for marketplace: `GET/POST /v1/marketplace/services`, `PATCH/DELETE .../services/{id}`, ratings
- [ ] **T13:** Create `APIRouter` for trust: `GET/POST /v1/trust/servers`, `GET .../servers/{id}/score`
- [ ] **T14:** Create `APIRouter` for identity: `POST /v1/identity/agents`, `GET .../agents/{id}`, keys, metrics
- [ ] **T15:** Create `APIRouter` for messaging: `GET/POST /v1/messaging/messages`, threads, negotiations
- [ ] **T16:** Create `APIRouter` for webhooks: `GET/POST /v1/webhooks`, deliveries, test
- [ ] **T17:** Create `APIRouter` for disputes: `GET/POST /v1/disputes`, respond, resolve
- [ ] **T18:** Remove `/v1/execute`, `/v1/batch`, and backward-compatibility redirects
- [ ] **T19:** Add `ETag` / `If-None-Match` support for read endpoints

### Priority 2 (HATEOAS)

- [ ] **T20:** Add `_links` with `self`, state transitions, and related resources to all responses
- [ ] **T21:** Add `Link` header for pagination (`rel="next"`, `rel="prev"`)
- [ ] **T22:** Add `GET /v1/` API root with service index and links
- [ ] **T23:** Add link templates for search endpoints (`{?query,category,limit}`)
- [ ] **T24:** Add `Vary: Authorization` header to enable CDN caching of public endpoints

### Cross-Cutting

- [ ] **T25:** Ensure all new endpoints pass through existing middleware (auth, rate limit, metrics, correlation ID, signing)
- [ ] **T26:** Ensure billing/metering works on new resource endpoints (use FastAPI dependency injection)
- [ ] **T27:** Add integration tests verifying resource endpoints against Pydantic response models
- [ ] **T28:** Update `/v1/onboarding` to showcase the RESTful endpoints
- [ ] **T29:** Update Python SDK to use resource endpoints
- [ ] **T30:** Update TypeScript SDK to use resource endpoints

---

## 8. What to Keep

1. **Rate limit headers** — Already follows standard patterns.
2. **Correlation IDs** — `X-Request-ID` propagation is correct.
3. **Security headers** — HSTS, CSP, X-Frame-Options are all correct.
4. **Pydantic `extra="forbid"`** — Strict request validation is essential.
5. **x402 payment protocol** — Innovative and well-designed.
6. **Tier-based access control** — Clean hierarchy, well-enforced.
7. **Response signing** — CRYSTALS-Dilithium/HMAC-SHA3 is forward-looking.
8. **Event streaming** — SSE + WebSocket dual-channel is comprehensive.
9. **Tool catalog** — `/v1/pricing` is a solid discovery mechanism.
10. **FastAPI auto-docs** — `/docs` (Swagger UI) and `/v1/openapi.json` are auto-generated.

---

## Appendix A: Reference Standards

- **Richardson Maturity Model:** https://martinfowler.com/articles/richardsonMaturityModel.html
- **RFC 9457 — Problem Details for HTTP APIs:** https://www.rfc-editor.org/rfc/rfc9457
- **IETF Idempotency-Key Header:** https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
- **HAL (Hypertext Application Language):** https://datatracker.ietf.org/doc/html/draft-kelly-json-hal
- **JSON:API Specification:** https://jsonapi.org/

## Appendix B: Changes from Previous Review

This review was updated to reflect:
1. **FastAPI migration** (from Starlette) — simplified OpenAPI/docs generation, APIRouter-based routing
2. **No current clients** — backward compatibility concerns removed, no sunsetting/deprecation phases needed
3. **Direct implementation** — collapsed 4 migration phases into 3 implementation phases (foundation, endpoints, HATEOAS)
4. **Removed obsolete items** — Starlette-specific references, RFC 8594 Sunset header (no APIs to sunset), SDK version bumping strategy
5. **Reduced TODO count** — from 32 to 30 (removed migration-specific tasks, added FastAPI-specific ones)
