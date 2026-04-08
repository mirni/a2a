# Prompt

Fix some of the findings from previous reports run against v0.9.6 (`reports/*-v0.9.6.md`).

## CMO report
* [x] Write AGENTS.md, SKILL.md, SDK READMEs
* [x] Fix pyproject.toml + package.json metadata
* [x] Implement /.well-known/agent-card.json
* [ ] Implement referral program and team tier — *PARTIAL: pricing.json config only, no runtime logic*
* [ ] Implement credit expiry — *PARTIAL: pricing.json config only, no enforcement code*


## CTO
* [x] Secure /metrics endpoint — IP allowlist (defaults to localhost)
* [x] Author 5 runbooks: gateway restart, DB recovery, Stripe webhook debug, error rate triage, disk emergency
* [x] Add scripts/dev_up.sh — docker-compose for full local stack
* [x] Add contract testing — 94 Hypothesis property-based tests in `gateway/tests/test_contract_models.py`
* [x] Add mutation testing — mutmut config in `gateway/pyproject.toml`, targeting `src/deps/`


## Architect
* [x] Author ADRs 002-009
* [x] Review connector testability and write tests that might be missing
* [x] Add monitoring/README.md + docs/sre/alerts.md
* [x] Complete Phase 2 gateway refactor — all 8 routers migrated, execute.py gates non-connector tools with 410
* [x] Audit OpenAPI and SDK alignment — SDK covers 34% (38 methods / 110 endpoints); disputes (0%), billing admin (17%) are main gaps; execute() covers all tools


## External auditor findings
* [x] Address findings reported in `reports/external/live-payments-audit-2026-04-05-combined.md` — C1-C4 all fixed
