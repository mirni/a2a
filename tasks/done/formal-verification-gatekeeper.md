# The "Formal Gatekeeper" Plugin Implementation Prompt

## Role
You are a Senior Formal Methods Engineer and Systems Architect. Your specialty is Formal Verification (FV) of autonomous systems and the Z3 SMT Solver.

## Objective
Implement the "Formal Gatekeeper" plugin for OpenClaw. This plugin acts as a mandatory verification proxy that intercepts an agent's PLAN.md and uses formal logic to prove it does not violate "Safety Invariants" before execution.

## Technical Specifications

### Invariant Engine (rules.py)
Define a library of safety properties in Z3/Python.
* System Safety: No unauthorized access to `/etc`, `/root`, or kernel parameters.
* Economic Safety: No single transaction > 10% of liquid balance; total daily gas < $5.00.
* Network Safety: No outbound connections to non-whitelisted IP ranges.

### Logic Translator (translator.py):
Develop a module that parses the agent's proposed PLAN.md (Markdown/JSON) and translates proposed shell commands and transactions into SMT-LIB logical statements.

### The Proof Loop:
The solver must check:
* Proposed_Action AND (NOT Safety_Invariant).
* If the result is UNSAT, the action is mathematically proven safe.
* If SAT, provide the Counter-example to the agent so it can self-correct.

### Proof Caching
To save on GPU cycles and tokens, implement a Proof Cache. If it has already proven that git push origin main is safe under the current invariants, it shouldn't re-run the Z3 solver for the same command.


### OpenClaw Integration (SKILL.md & tools.py):
* Hook into the OpenClaw "Pre-Execute" event.
* Implement an x402 Payment Hook: The plugin must autonomously request a micro-payment (e.g., 0.05 USDC) from the calling agent before returning the "Verified" status.

* Implemented as openclaw Plugin with a Skill interface
  ** As a Plugin (The Guard): It should use the onPreExecute lifecycle hook. This ensures that every time the AI tries to run a shell command or a transaction, the Gatekeeper intercepts it automatically. The AI cannot "forget" to use it.
  ** As a Skill (The Consultant): It provides a verify_logic tool. This allows the AI to proactively ask, "Hey, I'm thinking of this complex strategy; can you run a Z3 proof on it before I even put it in my plan?"


## Deliverables:
* `manifest.json`: Plugin metadata and permission scopes.
* `tools.py`: The Z3 implementation of the Formal Gatekeeper.
* `SKILL.md`: The OpenClaw operational instructions for the gatekeeping loop.
* `verification_test.py`: A suite of "Malicious Plans" that the solver must correctly block and "Safe Plans" it must approve.
*  Heavily commented test code that that exemplifies usage

## Tone
Academic rigor meets DevSecOps pragmatism. Every line of code should prioritize "Soundness" (no false positives for safety).

## Completed
- **Date**: 2026-04-09
- **PR**: (pending)
- **Summary**: Implemented the Formal Gatekeeper as a gateway product module with Z3 SMT verification via AWS Lambda.
  - Lambda handler (`lambda/z3-verifier/`) — Dockerfile + handler.py for Z3 solver execution
  - Product module (`products/gatekeeper/`) — models, storage, API with full TDD (47 tests)
  - Verifier connector (`products/connectors/verifier/`) — Lambda invocation client (9 tests)
  - Gateway integration — 6 tools, 6 REST endpoints, catalog entries, bootstrap + lifespan wiring
  - Full gateway test suite green (1527 tests)
