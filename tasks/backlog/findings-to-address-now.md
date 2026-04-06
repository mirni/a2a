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
* [ ] Add contract testing — *NOT DONE: hypothesis installed but unused*
* [ ] Add mutation testing — *NOT DONE: no mutmut config*


## Architect
* [x] Author ADRs 002-009
* [x] Review connector testability and write tests that might be missing
* [x] Add monitoring/README.md + docs/sre/alerts.md
* [ ] Complete Phase 2 gateway refactor (remove /execute.py) — *NOT DONE: execute.py still mounted*
* [ ] Audit OpenAPI and regenerate SDKs — *NOT DONE: SDK is hand-written*


## External auditor findings
* [x] Address findings reported in `reports/external/live-payments-audit-2026-04-05-combined.md` — C1-C4 all fixed
