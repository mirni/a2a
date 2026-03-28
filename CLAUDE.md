# Development Workflow: Strict TDD
You must follow a strict Test-Driven Development (TDD) cycle for all new features and bug fixes.

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
