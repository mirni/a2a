"""Tests for scripts/lint_no_float_money.py.

Guardrail: every ``float(x)`` call on a money-context variable under
gateway/src/routes, gateway/src/tools, gateway/src/deps/billing.py,
products/billing, products/payments, products/paywall must either be
removed or marked with ``# lint-no-float-money: allow``.

Background: v1.2.3..v1.2.7 external audits repeatedly caught cent-level
rounding bugs that traced back to ``float(decimal_value)`` on money
paths. This lint is the structural backstop so a future contributor
can't quietly reintroduce the class.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import lint_no_float_money as mod  # noqa: E402

# ---------------------------------------------------------------------------
# Single-file AST walking
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


def test_float_on_non_money_variable_is_clean(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "clean.py",
        """def f(x):
    ratio = float(x)
    return ratio
""",
    )
    assert mod.find_violations(f) == []


def test_float_on_amount_assignment_flagged(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "bad_amount.py",
        """def pay(x):
    amount = float(x)
    return amount
""",
    )
    violations = mod.find_violations(f)
    assert len(violations) == 1
    assert "amount" in violations[0].reason


def test_float_on_balance_assignment_flagged(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "bad_balance.py",
        """def top_up(raw):
    new_balance = float(raw)
    return new_balance
""",
    )
    assert len(mod.find_violations(f)) == 1


def test_float_on_fee_assignment_flagged(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "bad_fee.py",
        """def fee_calc(raw):
    gateway_fee = float(raw)
    return gateway_fee
""",
    )
    assert len(mod.find_violations(f)) == 1


def test_float_on_augmented_money_assignment_flagged(tmp_path: Path) -> None:
    """``total_cost += float(x)`` is just as broken as direct assignment."""
    f = _write(
        tmp_path,
        "bad_aug.py",
        """def tally(items):
    total_cost = 0.0
    for x in items:
        total_cost += float(x)
    return total_cost
""",
    )
    assert len(mod.find_violations(f)) >= 1


def test_float_on_money_compare_flagged(tmp_path: Path) -> None:
    """``if balance > float(x):`` reaches for float in a money comparison."""
    f = _write(
        tmp_path,
        "bad_cmp.py",
        """def check(balance, raw):
    if balance > float(raw):
        return True
    return False
""",
    )
    assert len(mod.find_violations(f)) == 1


def test_allow_comment_same_line_silences(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "allow_same.py",
        """def observe(x):
    amount = float(x)  # lint-no-float-money: allow (observability)
    return amount
""",
    )
    assert mod.find_violations(f) == []


def test_allow_comment_previous_line_silences(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "allow_prev.py",
        """def observe(x):
    # lint-no-float-money: allow (observability)
    amount = float(x)
    return amount
""",
    )
    assert mod.find_violations(f) == []


def test_float_argument_name_alone_triggers(tmp_path: Path) -> None:
    """``float(amount)`` without assignment context still flags because
    the *argument* looks like money."""
    f = _write(
        tmp_path,
        "bad_arg.py",
        """def send(amount):
    return str(float(amount))
""",
    )
    assert len(mod.find_violations(f)) == 1


def test_syntax_error_file_returns_no_violations(tmp_path: Path) -> None:
    """Malformed source is skipped, not crashed on."""
    f = _write(tmp_path, "broken.py", "def f(:\n")
    assert mod.find_violations(f) == []


def test_nonexistent_file_returns_no_violations(tmp_path: Path) -> None:
    missing = tmp_path / "ghost.py"
    assert mod.find_violations(missing) == []


# ---------------------------------------------------------------------------
# scan_paths — whole-tree behaviour
# ---------------------------------------------------------------------------


def test_scan_paths_aggregates_violations(tmp_path: Path) -> None:
    d = tmp_path / "pkg"
    d.mkdir()
    _write(
        d,
        "clean.py",
        """def f(x):
    ratio = float(x)
    return ratio
""",
    )
    _write(
        d,
        "dirty.py",
        """def pay(x):
    amount = float(x)
    return amount
""",
    )
    violations = mod.scan_paths([d])
    assert len(violations) == 1
    assert "dirty.py" in str(violations[0].path)


def test_scan_paths_ignores_non_py_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("amount = float(1.0)\n")
    (tmp_path / "config.yaml").write_text("amount: 1.0\n")
    assert mod.scan_paths([tmp_path]) == []


def test_scan_paths_accepts_single_file(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "solo.py",
        """def pay(x):
    amount = float(x)
    return amount
""",
    )
    violations = mod.scan_paths([f])
    assert len(violations) == 1


# ---------------------------------------------------------------------------
# Real-repo integration: the default scan must be clean
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).parent.parent.parent


def test_real_repo_default_scan_is_clean() -> None:
    """This is the guardrail. If it fails, a contributor reached for
    ``float()`` on a money-context variable. Convert to Decimal, or
    mark the line ``# lint-no-float-money: allow`` if this is an
    observability-only exposition path."""
    violations = mod.scan_paths(mod.DEFAULT_SCAN_PATHS)
    assert violations == [], "float() on money-context variables:\n" + "\n".join(
        f"  {v.path}:{v.line}  {v.snippet}" for v in violations
    )
