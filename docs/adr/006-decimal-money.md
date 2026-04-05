# ADR-006: Decimal Arithmetic for All Monetary Values

**Date:** 2026-03-30
**Status:** Accepted
**Role:** Architect

## Context

Floating-point arithmetic introduces rounding errors that compound
across many small operations. For a payments platform this is a
money-loss bug waiting to happen: `0.1 + 0.2 != 0.3` in IEEE 754.
We also need to round consistently across the codebase (debit half-cent
vs. credit half-cent leaks value either way).

## Decision

**All monetary values are `decimal.Decimal` internally and serialized
as strings on the wire** (never as JSON numbers).

- Internal type: `decimal.Decimal` with 6-decimal precision context
- Wire format: strings (`"10.00"`, `"0.005"`) in JSON request/response
- Rounding mode: `ROUND_HALF_EVEN` (banker's rounding) for display,
  `ROUND_DOWN` for fees the customer pays (never over-charge)
- Storage: SQLite `TEXT` columns, parsed back to Decimal on read
- Python `float` is **forbidden** for any currency field; `ruff` and
  code review enforce this

Pydantic models use `Decimal` with custom encoder to serialize as
string. Example:

```python
from decimal import Decimal
from pydantic import BaseModel

class Deposit(BaseModel):
    amount: Decimal
    model_config = {"json_encoders": {Decimal: str}}
```

## Alternatives Considered

- **`float`.** Unsafe — rounding errors compound. Rejected.
- **Integer cents (× 100).** Works for USD but breaks for multi-currency
  (some currencies have 0, 2, or 3 decimals). Rejected.
- **`decimal.Decimal` + JSON numbers.** Loses precision on the
  JavaScript side (all JS numbers are IEEE 754 doubles). Rejected.

## Consequences

### Positive

- Exact arithmetic for all money operations
- Wallet balance invariant (`SUM(balance) == total_issued - total_withdrawn`)
  holds to the cent, tested in CI
- Multi-currency-ready

### Negative

- Slightly more verbose code (`Decimal("10.00")` vs. `10.0`)
- Slower than `float` arithmetic (irrelevant at our volume)
- Wire format is strings — JavaScript clients must `new Decimal(str)`
  via a library or handle as strings

### Mitigations

- `sdk-ts/` wraps Decimal fields with `decimal.js` helpers
- Tests use `Decimal` literals throughout
- `mypy` + `ruff` flag any `float` in currency-adjacent code paths

## Related

- Code: `products/billing/src/types.py`, `gateway/src/serialization.py`
- Test: `gateway/tests/test_decimal_serialization.py`
- CLAUDE.md: "Use `Decimal` for all currency-related fields; never use `float`."
