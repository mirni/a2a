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


# Append all prompts and outputs into MASTER_LOG.md
* Both human prompt and claude terminal output should be appended.


# Use per-project memory, in workdir/.claude/memory.
Do not share memory between different projects.
