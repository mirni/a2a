# Ruff Linter — Action Items

**Total: 485 errors across the full repo.** 241 are auto-fixable with `ruff check --fix .`

CI runs `ruff check .` (line 32 of `.github/workflows/ci.yml`) — all 485 must be resolved.

---

## Phase 1: Auto-fix (241 errors, ~5 min)

Run `ruff check --fix .` to automatically resolve:

| Rule | Count | Description |
|------|-------|-------------|
| F401 | 150 | Unused imports — safe to remove |
| I001 | 59 | Unsorted import blocks — reorder only |
| F541 | 10 | f-string with no placeholders — convert to plain string |
| UP017 | 7 | `datetime.timezone.utc` → `datetime.UTC` |
| UP041 | 3 | `TimeoutError` alias cleanup |
| UP037 | 2 | Remove quotes from type annotations |
| UP045 | 2 | `Optional[X]` → `X | None` |
| F811 | 1 | Redefined-while-unused |
| UP006 | 1 | `Dict` → `dict` |
| SIM300 | 2 | Yoda conditions |
| **Subtotal** | **241** | |

Then run `ruff check --fix --unsafe-fixes .` for 69 more (review diff before committing):
- UP035 (7): `typing.Callable` → `collections.abc.Callable` etc.

**Command:**
```bash
ruff check --fix .
git diff --stat   # review
ruff check --fix --unsafe-fixes .
git diff --stat   # review again
```

---

## Phase 2: E402 — Module-level imports not at top (58 errors)

Most are caused by the bootstrap pattern:
```python
import gateway.src.bootstrap  # noqa: F401  (must run before product imports)
from billing_src.tracker import UsageTracker  # E402
```

**Fix:** Add `# noqa: E402` to lines after the bootstrap import, or restructure:
- `conftest.py` files (10 files × ~3 imports each = ~30 errors)
- `gateway/src/lifespan.py`, `benchmarks/` files

**Alternatively:** Add to `[tool.ruff.lint.per-file-ignores]` in each `pyproject.toml`:
```toml
[tool.ruff.lint.per-file-ignores]
"**/conftest.py" = ["E402"]
"gateway/benchmarks/*" = ["E402"]
```

---

## Phase 3: Manual fixes — correctness (48 errors)

### F841 — Unused variables (42 errors)
Files: across all products. Review each — some may be intentional (unpacking), most are dead code.
```bash
ruff check . --select F841 --output-format=grouped
```

### F821 — Undefined names (6 errors)
**Priority: HIGH** — these are real bugs or missing imports.
```bash
ruff check . --select F821 --output-format=grouped
```

---

## Phase 4: Manual fixes — code quality (66 errors)

### E501 — Line too long >120 chars (23 errors)
Break long lines. Most are in `batch.py` (fixed), `health_monitor.py`, test files.

### B904 — `raise ... from exc` missing (18 errors)
Add `from exc` to re-raises inside `except` blocks. Improves tracebacks.

### SIM105 — `try/except/pass` → `contextlib.suppress()` (17 errors)
Stylistic but cleaner. Some `S110` (7) overlap here — those also warn about logging.

### E731 — Lambda assignment (5 errors)
Convert `f = lambda x: ...` to `def f(x): ...`

### E741 — Ambiguous variable names (4 errors)
Rename `l`, `O`, `I` to clearer names.

### UP042 — Replace `str` enum (3 errors)
Use `StrEnum` instead of `str, Enum` base classes (Python 3.11+).

---

## Phase 5: Security warnings (26 errors, review only)

| Rule | Count | Action |
|------|-------|--------|
| S105 | 14 | Hardcoded password strings — likely test fixtures, add `# noqa: S105` |
| S106 | 9 | Hardcoded password in function args — same, test fixtures |
| S108 | 3 | `/tmp` paths — intentional defaults, add `# noqa: S108` |
| S608 | 2 | Hardcoded SQL — review for injection risk |

---

## Phase 6: Shadowing warnings (15 errors)

| Rule | Count | Action |
|------|-------|--------|
| A001 | 6 | Variable shadows builtin (e.g., `credits`, `type`) — rename |
| A002 | 8 | Argument shadows builtin — rename parameter |
| A004 | 1 | Import shadows builtin — rename |

---

## Recommended execution order

1. `ruff check --fix .` → commit as `style: auto-fix ruff issues (F401, I001, etc.)`
2. Fix E402 with per-file-ignores → commit as `style: suppress E402 for bootstrap pattern`
3. Fix F821 (undefined names) → commit as `fix: resolve undefined name references`
4. Fix F841 (unused vars) → commit as `fix: remove unused variables`
5. Fix B904, SIM105, E501 → commit as `style: improve exception chains and line lengths`
6. Fix S105/S106 with noqa → commit as `style: suppress test-fixture security warnings`
7. Fix A001/A002 renames → commit as `refactor: rename shadowed builtins`

After all phases: `ruff check .` should pass with 0 errors.
