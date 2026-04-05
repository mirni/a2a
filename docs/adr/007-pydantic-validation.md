# ADR-007: Pydantic Request Validation with `extra = "forbid"`

**Date:** 2026-03-30
**Status:** Accepted
**Role:** Architect

## Context

Mass-assignment vulnerabilities, silent typos, and API contract drift
are all preventable at the validation layer. We need strong input
validation that:

- Fails closed (rejects unknown fields)
- Produces machine-readable 400 errors
- Doubles as OpenAPI schema source
- Forces request/response shapes to be explicit and reviewable

## Decision

**Every API endpoint uses a Pydantic v2 model for request and response
bodies, with `model_config = {"extra": "forbid"}`.**

Rules:

1. Request models reject unknown fields with 400 `invalid_request`
2. Response models are declared explicitly (no `dict[str, Any]` leaks)
3. Every model includes a `json_schema_extra["example"]` used both for
   docs and for generating test payloads
4. Currency fields use `Decimal` (ADR-006)
5. String fields have `min_length`/`max_length` bounds
6. Enum fields use Python `Enum` classes, not `Literal` strings

Example:

```python
class DepositRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("10000"))
    description: str | None = Field(None, max_length=200)
    idempotency_key: str | None = Field(None, min_length=1, max_length=255)
    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "example": {"amount": "10.00", "description": "Top-up"},
        },
    }
```

## Alternatives Considered

- **`extra = "ignore"` (Pydantic default).** Silently drops typos
  (`amout` vs. `amount`) → customer confusion, support burden.
  Rejected.
- **Manual validation in handlers.** Duplicates logic, misses OpenAPI
  integration. Rejected.
- **Marshmallow / attrs / cattrs.** No meaningful advantage over
  Pydantic; FastAPI is already Pydantic-native. Rejected.

## Consequences

### Positive

- Typos caught at request boundary with clear error messages
- `extra = "forbid"` closes a mass-assignment attack class
- OpenAPI schema is auto-generated and always in sync
- Examples double as test fixtures:
  `DepositRequest.model_config["json_schema_extra"]["example"]`
- Pydantic v2 is fast (~50× Pydantic v1 for common cases)

### Negative

- Breaking API changes (adding required field) require clients to
  update — but they would anyway
- Slight boilerplate overhead vs. dict-based handlers

### Mitigations

- New non-breaking fields can be added as `Optional` with sensible
  defaults
- Deprecated fields live in the model for a full release before removal
- Contract tests pin the schema — see
  `gateway/tests/test_schema_contract.py` (future work)

## Related

- CLAUDE.md: "All API endpoints MUST use Pydantic models for
  request/response validation. `extra = "forbid"` must be enabled."
- ADR-004: RFC 9457 error format
- ADR-006: Decimal money
