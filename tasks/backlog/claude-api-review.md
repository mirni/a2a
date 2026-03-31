# API Design Review: Richardson Maturity Model Assessment

**Date:** 2026-03-31
**Reviewer Role:** Sr. Software Architect
**Scope:** Full A2A Commerce Gateway API surface (125+ tools, 15 services)

---

## Executive Summary

The A2A Commerce Gateway is a **Level 1** API with **partial Level 2** compliance. It uses a single-endpoint RPC pattern (`POST /v1/execute`) to dispatch 125+ tools, which is architecturally closer to JSON-RPC than REST. While this "universal gateway" pattern has operational simplicity, it sacrifices HTTP semantics, cacheability, and discoverability — all of which matter for a public-facing commerce API.

This review identifies concrete gaps against Richardson Maturity Model Levels 2 and 3, and provides an actionable refactoring plan.

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

This is custom. Consider adopting **RFC 9457 (Problem Details for HTTP APIs)**:
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

This is essentially JSON-RPC batching. In a RESTful design, batching is less necessary because each resource has its own endpoint, and clients can use HTTP/2 multiplexing for parallel requests.

### 2.6 Versioning

Current: URL path prefix `/v1/`. This is acceptable and widely used. However, the backward-compatibility redirects mix 301 (permanent) and 307 (temporary) for no clear reason.

### 2.7 Missing Standard Headers

| Header | Purpose | Current Status |
|--------|---------|----------------|
| `Idempotency-Key` | IETF standard for idempotent POST | Using body param `idempotency_key` instead |
| `Retry-After` | Indicate when to retry after 429 | Partially implemented |
| `ETag` / `Last-Modified` | Conditional GET | Not implemented |
| `Link` | Pagination, related resources | Not implemented |
| `Location` | Created resource URI (201) | Not implemented |
| `Deprecation` | RFC 8594 sunset header | Not implemented |

---

## 3. Proposed RESTful Resource Model (Level 2)

### 3.1 Resource Hierarchy

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

### 3.2 Response Format (Level 2)

**Resource response (no envelope):**
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

## 4. Proposed HATEOAS Additions (Level 3)

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

Instead of the current body parameter:
```json
{"tool": "create_intent", "params": {"idempotency_key": "txn-abc-123", ...}}
```

### 5.4 Use ISO 8601 Timestamps

Replace Unix epoch floats with ISO 8601 strings in all responses:

```json
// Current
{"created_at": 1711876496.123}

// Proposed
{"created_at": "2026-03-31T12:34:56.123Z"}
```

Unix timestamps are fine internally but ISO 8601 is the REST standard for APIs.

### 5.5 Use Consistent Decimal Serialization

All monetary amounts should serialize as strings to preserve precision:

```json
// Current (float)
{"balance": 500.0, "charged": 0.01}

// Proposed (string)
{"balance": "500.00", "charged": "0.01"}
```

### 5.6 ETags for Conditional GETs

For frequently-polled resources (balance, trust score, service listings):

```
GET /v1/billing/wallets/agent-123
→ ETag: "abc123"

GET /v1/billing/wallets/agent-123
If-None-Match: "abc123"
→ 304 Not Modified (no body, saves bandwidth)
```

### 5.7 OpenAPI Spec Alignment

The current OpenAPI spec at `/v1/openapi.json` documents the execute-based API. After refactoring, it should:
- Document each resource endpoint separately
- Include `Link` header schemas
- Include `_links` in response schemas
- Use `$ref` for shared models (ProblemDetail, PaginatedResponse, etc.)

---

## 6. Migration Strategy

### Phase 1: Level 2 Foundation (Non-Breaking)

Add RESTful resource endpoints **alongside** the existing `/v1/execute`:

1. **Read-only resource endpoints** — Add `GET /v1/billing/wallets/{id}`, `GET /v1/payments/intents/{id}`, etc. These call the same underlying tool functions.
2. **Standard headers** — Add `Idempotency-Key`, `Location`, `X-Charged` headers.
3. **RFC 9457 errors** — Add `Content-Type: application/problem+json` error responses. Keep old format on `/v1/execute`.
4. **Cursor pagination** — Add cursor support alongside offset.

**No breaking changes.** Both old and new endpoints work.

### Phase 2: Write Endpoints (Non-Breaking)

1. **POST for creates** — `POST /v1/payments/intents` returns `201 Created` with `Location` header.
2. **Action sub-resources** — `POST /v1/payments/intents/{id}/capture` instead of `POST /v1/execute {"tool": "capture_intent"}`.
3. **PATCH for updates** — `PATCH /v1/marketplace/services/{id}` instead of `POST /v1/execute {"tool": "update_service"}`.
4. **DELETE for removals** — `DELETE /v1/trust/servers/{id}`.

### Phase 3: HATEOAS & Deprecation

1. **Add `_links`** to all resource responses.
2. **Add API root** — `GET /v1/` returns service index with links.
3. **Deprecate `/v1/execute`** — Add `Deprecation` header (RFC 8594) and `Sunset` date.
4. **Update SDK** — Python and TypeScript SDKs generate methods from OpenAPI spec.

### Phase 4: Cleanup

1. **Remove `/v1/execute`** after sunset period (6-12 months).
2. **Remove `/v1/batch`** — HTTP/2 multiplexing replaces it.
3. **Version bump** — Consider `/v2/` if breaking changes accumulate.

---

## 7. Actionable TODO List

### Priority 0 (Do First — Foundation)

- [ ] **T1:** Create ADR `docs/adr/002-restful-resource-model.md` documenting the decision to move from RPC to REST
- [ ] **T2:** Define the full resource URL hierarchy in a new PRD `docs/prd/015-rest-api-refactor.md`
- [ ] **T3:** Adopt RFC 9457 (Problem Details) error format alongside the current format
- [ ] **T4:** Adopt `Idempotency-Key` request header (IETF standard) alongside body parameter
- [ ] **T5:** Add `201 Created` + `Location` header for POST endpoints that create resources
- [ ] **T6:** Serialize all monetary values as strings in JSON responses (Decimal precision)
- [ ] **T7:** Serialize all timestamps as ISO 8601 strings in responses

### Priority 1 (Level 2 — Resource Endpoints)

- [ ] **T8:** Add `GET /v1/billing/wallets/{agent_id}` (maps to `get_balance` tool)
- [ ] **T9:** Add `GET /v1/billing/wallets/{agent_id}/transactions` (maps to `get_transactions`)
- [ ] **T10:** Add `POST /v1/payments/intents` and `GET /v1/payments/intents/{id}` (maps to `create_intent`, `get_intent`)
- [ ] **T11:** Add `POST /v1/payments/intents/{id}/capture` (maps to `capture_intent`)
- [ ] **T12:** Add `POST /v1/payments/escrows` and `GET /v1/payments/escrows/{id}` (maps to `create_escrow`, `get_escrow`)
- [ ] **T13:** Add `GET /v1/marketplace/services` and `POST /v1/marketplace/services` (maps to `search_services`, `register_service`)
- [ ] **T14:** Add `GET /v1/trust/servers/{id}/score` (maps to `get_trust_score`)
- [ ] **T15:** Add cursor-based pagination to all list endpoints
- [ ] **T16:** Add `ETag` / `If-None-Match` support for read endpoints
- [ ] **T17:** Move `charged` and `request_id` from response body to `X-Charged` and `X-Request-ID` headers

### Priority 2 (Level 3 — HATEOAS)

- [ ] **T18:** Add `_links` with `self`, state transitions, and related resources to all responses
- [ ] **T19:** Add `Link` header for pagination (`rel="next"`, `rel="prev"`)
- [ ] **T20:** Add `GET /v1/` API root with service index and links
- [ ] **T21:** Add link templates for search endpoints (`{?query,category,limit}`)

### Priority 3 (Deprecation & Cleanup)

- [ ] **T22:** Add `Deprecation` header (RFC 8594) to `/v1/execute` responses
- [ ] **T23:** Update OpenAPI spec to document both old and new endpoints
- [ ] **T24:** Update Python SDK to use resource endpoints
- [ ] **T25:** Update TypeScript SDK to use resource endpoints
- [ ] **T26:** Create migration guide for API consumers
- [ ] **T27:** Remove `/v1/execute` after sunset period

### Cross-Cutting Concerns

- [ ] **T28:** Ensure all new endpoints pass through existing middleware (auth, rate limit, metrics, correlation ID, signing)
- [ ] **T29:** Ensure billing/metering works on both old and new endpoints during transition
- [ ] **T30:** Add integration tests verifying old and new endpoints return equivalent data
- [ ] **T31:** Update `/v1/onboarding` to showcase the new RESTful endpoints
- [ ] **T32:** Add `Vary: Authorization` header to enable CDN caching of public endpoints

---

## 8. What to Keep

Not everything needs to change. These aspects of the current design are already good:

1. **`POST /v1/execute` as a fallback** — Useful for AI agents that prefer a single-endpoint RPC style. Keep it available (just not the only option).
2. **Rate limit headers** — Already follows standard patterns.
3. **Correlation IDs** — `X-Request-ID` propagation is correct.
4. **Security headers** — HSTS, CSP, X-Frame-Options are all correct.
5. **Pydantic `extra="forbid"`** — Strict request validation is essential.
6. **x402 payment protocol** — Innovative and well-designed.
7. **Tier-based access control** — Clean hierarchy, well-enforced.
8. **Response signing** — CRYSTALS-Dilithium/HMAC-SHA3 is forward-looking.
9. **Event streaming** — SSE + WebSocket dual-channel is comprehensive.
10. **Tool catalog** — `/v1/pricing` is a solid discovery mechanism.

---

## 9. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Breaking existing API consumers | Non-breaking migration: old endpoints stay active during transition |
| Increased route complexity | Use Starlette route groups with shared middleware |
| Billing duplication | Extract billing into middleware that works on both old and new routes |
| Test coverage gaps | T30: equivalence tests between old/new endpoints |
| Performance regression from more routes | Starlette routing is O(n) but fast; 50 routes adds <1ms |
| SDK breaking changes | Version bump SDKs (v2), keep v1 SDK working against old endpoints |

---

## Appendix A: Reference Standards

- **Richardson Maturity Model:** https://martinfowler.com/articles/richardsonMaturityModel.html
- **RFC 9457 — Problem Details for HTTP APIs:** https://www.rfc-editor.org/rfc/rfc9457
- **RFC 8594 — Sunset Header:** https://www.rfc-editor.org/rfc/rfc8594
- **IETF Idempotency-Key Header:** https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
- **HAL (Hypertext Application Language):** https://datatracker.ietf.org/doc/html/draft-kelly-json-hal
- **JSON:API Specification:** https://jsonapi.org/
