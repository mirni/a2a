# Development Workflow: Test-Driven Development (TDD)
You must follow a strict Test-Driven Development (TDD) cycle for all new features and bug fixes in the product or gateway code.

## 1. Red Phase (Failing Test)
- **Action:** Before touching any source code, write a new test case in the appropriate test file.
- **Verification:** Run the test command and confirm that the new test fails (and only the new test).
- **Rule:** Do not proceed until you have explicitly shown the failing test output in the terminal.

## 2. Green Phase (Pass Test)
- **Action:** Write the minimum amount of code necessary in the source file to make the failing test pass.
- **Rule:** Avoid "pre-coding" future functionality. Focus only on the current failure.

## 3. Refactor Phase (Clean Up)
- **Action:** Review the code for readability and efficiency.
- **Verification:** Run the full test suite again to ensure the refactor didn't break anything.

Infrastructure code is exempt from this rule.

## Git/Github Workflow: Feature Branch Model
* Never push directly to `main`. Always create a feature/fix branch, commit there, and open a PR.
* Branch naming: `feat/<name>`, `fix/<name>`, `refactor/<name>`, etc.
* Push branches using the `GITHUB_DEPLOYMENT_TOKEN` from `.env` (already configured in `.git/config` — do not strip it).
* Open PRs with `gh pr create`. CI runs automatically on all branches and PRs. Make sure that the CI pipeline is all green before you are done -- fix and iterate autonomously if pipeline fails.
* PRs should be merged to `main` by human, unless instructed otherwise. Squash merge is used for PRs unless author (agent) instructs in the PR comment otherwise. E.g. a prompt with todo list with 5 multiple agents working individually should produce just one PR with 5 partial results merged into a feature branch (for the PR) and a comment "do not squash", since the partial work should be kept as separate commits.
* Required status checks before merge: all CI jobs must be green before merging, including staging.
* Staging deployment runs automatically on PRs to `main` (via Tailscale — secrets `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `TAILSCALE_IP` are configured).
* Production deployment is manual via `workflow_dispatch` on `main` with approval gate.

## Packaging
* Debian packages are built via `scripts/create_package.sh` (not the old `packaging/` dir).
* Package definitions live in `package/` with symlinks to repo content.
* Available packages: `a2a-gateway` (prod), `a2a-gateway-test` (staging), `a2a-website`, `a2a-sdk` (wheel).
* Build all: `scripts/create_package.sh ALL`. Build one: `scripts/create_package.sh a2a-gateway`.
* Output goes to `dist/`.

## General coding guidelines:
* Keep functions small and "pure". Follow Single Responsibility Principle. Prefer "Pure Functions" (functions that don't change state) for your transaction calculation logic.
* Every model must include a `schema_extra` or `json_schema_extra` example for documentation. This can be used in tests to generate a valid test payload (e.g. `AgentTransaction.Config.schema_extra["example"]`), and to make sure test and documentation are always in-sync.
* Use Input Randomization and Contract Testing (with example acting as the "Golden Standard" for the contract): Use libraries like Hypothesis where it makes sense in the tests.
* Use Negative Testing: Specifically write tests that must fail. E.g.: "Send a Stripe refund request with an expired JWT. Confirm it returns 401 Unauthorized and logs the attempt."


## Security & Validation
* All API endpoints MUST use Pydantic models for request/response validation.
* `extra = "forbid"` must be enabled on all request models.
* Use `Decimal` for all currency-related fields; never use `float`.


## Database Schema Migrations
* Never execute schema changes within the application process.
* All schema modifications must be scripted as Migration objects and applied via `scripts/migrate_db.sh`.
* `_SCHEMA` DDL must always reflect the current expected state (post-migration) so fresh DBs get the full schema without needing migrations.
* The app checks schema version on startup and fails with `SchemaVersionMismatchError` if the DB hasn't been migrated.


# Append all prompts and outputs into logs/MASTER_LOG.md
* Both human prompt and claude terminal output should be appended.


# Document Organization

## Directory layout
```
CLAUDE.md              # Permanent coding rules (this file)
README.md              # Project overview
CHANGELOG.md           # Release history
docs/                  # Reference documentation (stable)
  infra/               # Infrastructure & ops docs
  adr/                 # Architecture Decision Records
  prd/                 # Product Requirements Documents
  blog/                # Blog posts
  api-reference.md     # API docs
reports/               # Analysis & research output (read-only, gitignored)
  customer/            # Customer agent analysis reports
  archive/             # Historical reports & plans
tasks/                 # Human ↔ Claude task queue
  backlog/             # Pending tasks — human drops prompts here
  active/              # Currently being worked on
  done/                # Completed (moved here after completion)
  external/            # External audit results and third-party reports
logs/                  # Session logs (append-only)
  MASTER_LOG.md        # Full session transcript
plans/                 # Living strategic/planning documents
```

## Task workflow
* **Human**: create one `.md` file per task in `tasks/backlog/` with a clear prompt.
* **Claude**: at session start, check `tasks/backlog/` for pending work.
* **Claude**: move file to `tasks/active/` when starting, to `tasks/done/` when complete.
* **Claude**: add a `## Completed` section at the bottom of finished task files (date, PR#, summary).
* Never create new `.md` files in the repo root. Use the appropriate directory above.
* Reports and analysis go in `reports/`, not `docs/` or root.

## PR workflow
* One PR per session consolidating all work. Avoid multiple parallel PRs.
* Do not merge PRs — leave for human review. All CI jobs (including staging) must be green.


# Use per-project memory, in workdir/.claude/memory.
Do not share memory between different projects.
