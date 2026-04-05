# ADR-004: RFC 9457 Problem Details for HTTP Errors

**Date:** 2026-03-30
**Status:** Accepted
**Role:** Architect

## Context

Error responses need to be structured, discoverable, and stable across
SDK versions. Ad-hoc JSON like `{"error": "nope"}` loses information
(error class, correlation ID, retry hint) and breaks client code when
we refine the message wording.

## Decision

**All non-2xx responses from the gateway follow RFC 9457 "Problem
Details for HTTP APIs"**, emitted via
`gateway/src/errors.py::error_response`.

Response shape:

```json
{
  "type": "https://api.greenhelix.net/errors/insufficient_funds",
  "title": "Insufficient funds",
  "status": 402,
  "detail": "Wallet 'agent-123' has 5.00 credits; 10.00 required.",
  "instance": "/v1/execute?request_id=req_abc123",
  "code": "insufficient_funds",
  "agent_id": "agent-123",
  "required": "10.00",
  "available": "5.00"
}
```

- `Content-Type: application/problem+json`
- `code` is a stable snake_case identifier SDKs match on
- `type` is an absolute URL to the error documentation
- `instance` includes the request_id for log correlation
- Extra fields (`agent_id`, `required`, etc.) are error-specific and
  documented per-error-class

A custom `FastAPI.exception_handler` maps product exceptions (defined in
`products/<product>/src/errors.py`) to HTTP status + problem details via
a registry: `_PRODUCT_EXC_NAMES` in `gateway/src/app.py`.

## Alternatives Considered

- **Ad-hoc `{"error": "..."}` JSON.** No stable code field, hard to
  match on in SDKs. Rejected.
- **GraphQL-style `errors: [{...}]` arrays.** We're REST; mixing models
  confuses clients. Rejected.
- **JSON:API error objects.** Similar to RFC 9457 but heavier; RFC
  9457 is IETF-standardized and simpler.

## Consequences

### Positive

- SDK error classes map 1:1 to `code` values — type-safe in all SDKs
- Errors are self-describing (URL → docs)
- Debuggable: every error carries `instance` with request_id
- Testable: error-class contracts enforced by unit tests

### Negative

- More code to write vs. bare strings
- `type` URLs need to resolve to actual documentation pages (otherwise
  the affordance is broken)

### Mitigations

- `error_response()` is a single helper used by all handlers
- Error docs auto-generated from product exception classes (future)

## Related

- Code: `gateway/src/errors.py`, `products/shared/src/errors.py`
- Test: `gateway/tests/test_error_response_format.py`
- Spec: https://www.rfc-editor.org/rfc/rfc9457
