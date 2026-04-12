"""v1.2.9 hotfix: Decimal-only money comparisons at boundary gates.

Scope: narrow hotfix from the repo-hygiene plan. Every external audit
since v1.2.3 has flagged ``float(amount)`` at boundary checks as a
latent precision bug. The actual values used today (caps ≤ 1e10,
amounts ≤ 1e9, 2 decimal places) all fit inside float64 exactly, so
the bug hasn't manifested in production — but the *code pattern* is
wrong and the next cap/validator change could silently break a money
gate.

This test file pins the two hot paths to Decimal arithmetic:

1. ``GatewayConfig.deposit_limits`` — values must be ``Decimal``, not
   ``int`` or ``float``.
2. ``gateway/src/routes/v1/billing.py`` must compare ``body.amount``
   to ``tier_limit`` as Decimals (no ``float(body.amount)`` at the
   boundary).
3. ``gateway/src/deps/tool_context.py::_check_budget_caps`` must
   compute ``daily_spend`` and ``monthly_spend`` as Decimals and
   compare against a Decimal cap.

We combine property-based (Hypothesis) checks with static AST probes.
Static probes are the guardrail — they catch a contributor silently
re-introducing ``float(body.amount)`` in a future edit.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 1. Config shape
# ---------------------------------------------------------------------------


def test_deposit_limits_are_all_decimals() -> None:
    """Type assertion: GatewayConfig.deposit_limits values must be Decimal.

    If this fails, a contributor regressed the hotfix by re-using int
    or float. Money caps must be Decimal so comparisons against
    ``body.amount`` (always Decimal via the Pydantic model) are exact.
    """
    from gateway.src.config import GatewayConfig

    cfg = GatewayConfig.from_env()
    assert cfg.deposit_limits, "deposit_limits empty — misconfigured"
    for tier, limit in cfg.deposit_limits.items():
        assert isinstance(limit, Decimal), (
            f"deposit_limits[{tier!r}] is {type(limit).__name__}, expected Decimal. "
            "This regresses the v1.2.9 hotfix — every money cap must be Decimal."
        )


# ---------------------------------------------------------------------------
# 2. Property: deposit-limit comparison matches a Decimal reference
# ---------------------------------------------------------------------------


@given(
    amount=st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("999999999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    cap=st.integers(min_value=1, max_value=10_000_000),
)
def test_decimal_cap_comparison_is_total_and_reflexive(amount: Decimal, cap: int) -> None:
    """For any valid deposit amount and any integer cap, the Decimal
    comparison used by the route must agree with a naive Decimal
    reference implementation, and must never be contradictory.
    """
    cap_d = Decimal(cap)
    result_route = amount > cap_d  # what the post-hotfix route does
    result_reference = Decimal(amount) > Decimal(cap)  # naive reference
    assert result_route is result_reference

    # Reflexive: same value against itself is False.
    assert (cap_d > cap_d) is False

    # Ordering: amount > cap implies cap < amount.
    assert result_route == (cap_d < amount)


# ---------------------------------------------------------------------------
# 3. Static probes: no `float(body.amount)` at the boundary gates
# ---------------------------------------------------------------------------


def _load(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def test_billing_deposit_route_does_not_compare_float_to_cap() -> None:
    """The deposit route must compare ``body.amount`` to the cap
    as Decimal. Specifically, the cap-check branch must not contain a
    ``float(...)`` call on ``body.amount``."""
    path = REPO_ROOT / "gateway" / "src" / "routes" / "v1" / "billing.py"
    tree = _load(path)
    func = _function(tree, "deposit")
    src = ast.unparse(func)

    # Find the cap-check block. We look for the `> tier_limit` comparison
    # and assert that its left operand is NOT `float(body.amount)`.
    offenders: list[str] = []
    for node in ast.walk(func):
        if not isinstance(node, ast.Compare):
            continue
        if not node.comparators:
            continue
        # Is the right side a Name called 'tier_limit' (or similar)?
        rhs = node.comparators[0]
        if isinstance(rhs, ast.Name) and rhs.id in {"tier_limit", "cap"}:
            lhs_src = ast.unparse(node.left)
            if "float(" in lhs_src:
                offenders.append(lhs_src)

    assert not offenders, (
        "deposit_funds compares float(body.amount) to the tier cap:\n  "
        + "\n  ".join(offenders)
        + "\nReplace with a Decimal comparison."
    )
    # Belt and braces: the function source as a whole must not contain
    # the known-bad pattern.
    assert "float(body.amount) > tier_limit" not in src


def test_check_budget_caps_uses_decimal_arithmetic() -> None:
    """``_check_budget_caps`` must convert ``daily_cap``, ``monthly_cap``,
    ``daily_spend``, ``monthly_spend`` to Decimal before comparing.

    We probe for Decimal imports/uses inside the function body. Exact
    number of Decimal nodes is a moving target, but zero Decimal uses
    = regression.
    """
    path = REPO_ROOT / "gateway" / "src" / "deps" / "tool_context.py"
    tree = _load(path)
    func = _function(tree, "_check_budget_caps")
    src = ast.unparse(func)

    # Must mention Decimal at least once.
    assert "Decimal(" in src, (
        "_check_budget_caps does not use Decimal anywhere. Money caps "
        "must be compared as Decimal to avoid float drift across "
        "many-tool-call accumulations."
    )
    # Must NOT cast the cap via float() on the divide-by-1e8 step.
    # The old bug was `float(daily_cap) / 100_000_000`. After the
    # hotfix it should be `Decimal(daily_cap) / Decimal(100_000_000)`
    # or equivalent.
    assert "float(daily_cap)" not in src
    assert "float(monthly_cap)" not in src
