# First Proof in 60 Seconds

Prove a business invariant with a Z3-backed formal verification — end to
end, from `pip install` to a signed proof hash — in under a minute.

> **Who this is for.** Agent developers who need to show that a claim
> about their agent's behaviour (e.g. *"the wallet never goes negative"*
> or *"trade size stays within risk limits"*) is mathematically sound,
> not just tested.

---

## 0. Prerequisites

- Python 3.10+
- An A2A Commerce **pro-tier** API key
  ([sign up](https://a2acommerce.com/signup), then upgrade in the
  dashboard — gatekeeper is paid-only to protect the solver pool)
- 60 seconds

---

## 1. Install the SDK — 10s

```bash
pip install a2a-client
```

## 2. Write the policy — 20s

Create a file `first_proof.py`. The policy below asserts that an integer
variable `x` lies in the open interval `(0, 10)` — a trivial example, but
the same syntax scales to multi-variable inequalities, mod arithmetic,
and linear real algebra.

```python
import asyncio

from a2a_client import A2AClient
from a2a_client.verifier import prove_policy


async def main() -> None:
    policy = {
        "name": "x_in_range",
        "variables": [
            {"name": "x", "type": "int", "value": 5},
        ],
        "assertions": [
            {"op": ">", "args": ["x", 0]},
            {"op": "<", "args": ["x", 10]},
        ],
    }

    async with A2AClient(api_key="a2a_pro_...") as client:
        result = await prove_policy(client, "my-agent-id", policy)
        print(f"satisfied={result.satisfied}")
        print(f"proof_hash={result.proof_hash}")
        print(f"job_id={result.job_id}")


asyncio.run(main())
```

## 3. Run it — 5s

```bash
python first_proof.py
```

Expected output:

```
satisfied=True
proof_hash=b89d7e7f4a…
job_id=vj-c4a22355319…
```

The `proof_hash` is the SHA3-256 of the Z3 proof artifact. You can
publish it on-chain, embed it in a receipt, or share it with a
counterparty — they can then call ``verify_proof`` against the A2A
gateway to independently confirm the claim.

## 4. (Optional) Verify from another party — 25s

On the *receiving* agent side:

```python
from a2a_client import A2AClient

async with A2AClient(api_key="a2a_free_...") as auditor:
    check = await auditor.verify_proof(proof_hash="b89d7e7f4a…")
    assert check.valid, f"proof rejected: {check.reason}"
```

`verify_proof` is a **free-tier** endpoint — anyone can verify, only
provers pay. This keeps the economics right: the cost of a claim sits
with the party making the claim, the benefit of auditability spreads to
the whole network.

---

## What just happened

1. The SDK serialised your JSON policy and submitted it to
   ``POST /v1/gatekeeper/jobs`` (`submit_verification`).
2. The gateway routed the job to an AWS Lambda running Z3 4.13.4
   (us-east-1 with automatic failover to us-west-2 — see
   `docs/infra/AWS_Z3_VERIFIER_SETUP.md`).
3. Z3 returned SAT (a model exists: `x = 5` satisfies both constraints),
   which the gatekeeper records as `result="satisfied"`.
4. A signed proof artifact (Ed25519 over the SMT2 + result + timestamp)
   was stored; its SHA3-256 is returned as `proof_hash`.
5. The SDK polled ``GET /v1/gatekeeper/jobs/{id}`` until terminal,
   folded the raw response into a typed `ProofResult`, and handed it to
   your code.

## Pricing

Per the v1.2.4 pricing reset (2026-04-10), each proof costs:

| Component | Rate |
|---|---|
| Base | 10 credits |
| Per-property | 2 credits |
| Solver time | 1 credit per second of wall-clock Z3 time |

Trivial proofs land around **12 credits**. Complex proofs — dozens of
properties, or solver times of 10s+ — scale up to protect the queue.
There is **no free tier** for verification; abuse of a shared SMT solver
at free rates is how other platforms have gone dark.

See `docs/infra/GATEKEEPER_PRICING.md` for the full rationale.

## Next steps

- **Supported policy DSL.** Read `docs/infra/GATEKEEPER_JSON_POLICY.md`
  for the full grammar (operators, types, bound variables, functions).
- **Raw SMT2.** If you already have an SMT-LIB2 file, skip
  `prove_policy` and call ``submit_verification`` directly with
  ``language="smt2"``.
- **MCP integration.** The same gatekeeper tools are exposed over MCP —
  point Claude Desktop at `a2a-mcp-server` and it will see
  `submit_verification`, `get_verification_status`, `verify_proof` in
  its tool list.
- **On-chain receipts.** Pair `proof_hash` with a payment receipt from
  `/v1/payments/intents` to get an atomically-proven, atomically-paid
  obligation — the core primitive for reputable agent commerce.
