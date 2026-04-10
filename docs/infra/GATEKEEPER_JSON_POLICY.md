# Gatekeeper JSON Policy Language

**Status**: v1.2.2 (2026-04-10)

The Gatekeeper formal verification service accepts two property
languages:

| language      | expression format          | who writes it           |
|---------------|----------------------------|-------------------------|
| `z3_smt2`     | raw [SMT-LIB 2] text       | power users familiar with Z3 |
| `json_policy` | structured JSON AST        | everyone else — compiled server-side to `z3_smt2` |

The JSON policy DSL is the recommended entry point: it is easier to
read, diff, and template than raw SMT-LIB2, and the server rejects
malformed policies at submission time with a standard 400 error so you
never pay for broken jobs.

---

## At a glance

```json
{
  "name": "balance_conservation",
  "description": "All user balances are non-negative and sum to the fixed total supply",
  "variables": [
    {"name": "alice", "type": "int"},
    {"name": "bob",   "type": "int"},
    {"name": "total", "type": "int", "value": 1000}
  ],
  "assertions": [
    {"op": ">=", "args": ["alice", 0]},
    {"op": ">=", "args": ["bob",   0]},
    {
      "op": "==",
      "args": [
        {"op": "+", "args": ["alice", "bob"]},
        "total"
      ]
    }
  ]
}
```

The server compiles this deterministically to:

```smt2
(declare-const alice Int)
(declare-const bob Int)
(declare-const total Int)
(assert (= total 1000))
(assert (>= alice 0))
(assert (>= bob 0))
(assert (= (+ alice bob) total))
```

and hands it to Z3 unchanged. **The same JSON always produces the same
SMT2**, so proof hashes stay reproducible.

---

## Schema

```json
{
  "name":        "string, 1-128 chars, required",
  "description": "string, 0-1000 chars, optional",
  "variables":   [ PolicyVariable, ... ],
  "assertions":  [ Expression,     ... ]
}
```

### `variables[]` — `PolicyVariable`

```json
{
  "name":  "identifier, [A-Za-z_][A-Za-z0-9_]*",
  "type":  "int" | "real" | "bool",
  "value": optional int/float/bool (emits an extra equality assertion)
}
```

- Up to 64 variables per policy.
- Variable names must be unique.
- If you supply `value`, the compiler emits `(assert (= name <value>))`,
  turning the variable into a bound constant. Handy for declaring
  parameters like `total_supply = 1000` without needing a separate
  assertion.

### `assertions[]` — `Expression`

Each entry is recursively either:

- a **literal** — int, float, or bool
- a **variable reference** — any string that matches a declared
  variable name
- an **operator node** — `{"op": "<op>", "args": [...]}`

Supported operators:

| category    | JSON op                               | SMT2       |
|-------------|---------------------------------------|------------|
| arithmetic  | `+`, `-`, `*`, `/`                    | same        |
| comparison  | `==`                                  | `=`        |
| comparison  | `!=`                                  | `distinct` |
| comparison  | `<`, `<=`, `>`, `>=`                  | same       |
| boolean     | `and`, `or`, `not`                    | same       |
| boolean     | `=>`                                  | `=>`       |

Up to **256 assertions** per policy (hard cap).

### Compile-time errors

The server raises `InvalidPolicyError` (HTTP 400, `code=invalid_policy`)
when:

- the expression field is not valid JSON
- the JSON does not satisfy the `JsonPolicy` schema
- an operator is unknown (`{"op": "bogus", ...}`)
- an expression references an undeclared variable
- a boolean variable is assigned a non-bool constant

You pay zero credits for policies rejected at admission.

---

## Submitting a JSON policy

```bash
curl -X POST https://api.greenhelix.net/v1/gatekeeper/jobs \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agent-alice",
    "properties": [
      {
        "name": "positive_balance",
        "language": "json_policy",
        "expression": "{\"name\":\"positive_balance\",\"variables\":[{\"name\":\"balance\",\"type\":\"int\"}],\"assertions\":[{\"op\":\">\",\"args\":[\"balance\",0]}]}"
      }
    ]
  }'
```

The `expression` field is a **JSON-encoded string** — i.e. the entire
policy serialised inside the outer request body. This keeps the wire
format identical to `z3_smt2` submissions and means you can mix
languages within a single job.

You can also submit multiple properties in different languages in the
same call, and the server compiles each one appropriately:

```json
"properties": [
  {"name": "p1", "language": "z3_smt2",     "expression": "(declare-const x Int)\n(assert (> x 0))"},
  {"name": "p2", "language": "json_policy", "expression": "{...}"}
]
```

---

## Worked examples

The repository ships a set of ready-to-use policies under
[`products/gatekeeper/policies/examples/`](../../products/gatekeeper/policies/examples/).

| file | what it proves |
|------|-----------------|
| `balance_conservation.json` | user balances sum to a fixed total |
| `withdraw_guard.json`       | every withdrawal is backed by sufficient balance |
| `fee_bounded.json`          | fee rate stays within `[0, 10%]` |
| `escrow_state_machine.json` | escrow is in exactly one of funded/released/refunded |
| `rate_limit_ok.json`        | current request count is within the tier allowance |

Copy, tweak, then POST — the examples double as smoke tests, so they
are guaranteed to compile and to be accepted by the Lambda verifier.

---

## Billing

- You are charged the base cost (`5 credits`) + `1 credit` per property,
  regardless of result (`satisfied` / `violated` / `unknown`).
- **You are not charged** when a job ends in a `FAILED` or `ERROR`
  state caused by a verifier-side problem (unreachable Lambda, Z3 parse
  error inside the backend, etc.). The charge is waived before the
  response is written to the wallet. See audit finding **CRIT-2** in
  `reports/external/multi-persona-audit-v1.2.1-2026-04-10.md`.
- Policies rejected at admission (HTTP 400) incur no charge.

---

## Design rationale

- **Single source of truth** — storage keeps the original policy (JSON
  or SMT2), so a later `GET /v1/gatekeeper/jobs/{id}` can show the
  integrator exactly what they submitted. The SMT2 is generated JIT
  inside `_execute_job`.
- **Deterministic compilation** — variable declarations follow the
  declared order, constant bindings come next, then assertions. Same
  input → same bytes → same proof hash.
- **No operator surprises** — the compiler rejects unknown operators
  and undeclared variables; there is no implicit coercion and no
  template expansion.

[SMT-LIB 2]: http://smtlib.cs.uiowa.edu/papers/smt-lib-reference-v2.6-r2021-05-12.pdf
