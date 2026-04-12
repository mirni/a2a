#!/usr/bin/env python3
"""Lint: ``float(...)`` must not appear inside money arithmetic.

The v1.2.3..v1.2.7 external audits repeatedly caught off-by-a-cent
bookkeeping bugs. Every single one traces back to somewhere we reach
for ``float()`` on a value that started life as ``Decimal``. The
budget-cap gate, the refund ledger, the split-intent allocator — all
of these lost cents through IEEE-754 rounding the moment their
operands touched binary floats.

This linter is a cheap, AST-only guard that rejects ``float(x)`` in a
statement where ``x`` is assigned to or compared against a variable
whose name looks like money (``amount``, ``balance``, ``cost``,
``fee``, ``credit``, ``price``, ``spend``, ``cap``, ``deposit``,
``refund``, ``capture``, ``payout``). Files or specific lines can be
whitelisted via an inline ``# lint-no-float-money: allow`` comment
when the conversion is genuinely for observability exposition (e.g.
Prometheus counter emission).

Usage:
    python scripts/lint_no_float_money.py                    # default scan
    python scripts/lint_no_float_money.py path/to/file.py
    python scripts/lint_no_float_money.py --quiet

Exit codes:
    0  no violations
    1  one or more violations
    2  invalid invocation
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Default scan: every place that handles money. Scoped narrowly so we
# don't chase false positives in test files, observability counters,
# or the SDK's float-compat layer.
DEFAULT_SCAN_PATHS = [
    REPO_ROOT / "gateway" / "src" / "routes" / "v1",
    REPO_ROOT / "gateway" / "src" / "tools",
    REPO_ROOT / "gateway" / "src" / "deps" / "billing.py",
    REPO_ROOT / "gateway" / "src" / "deps" / "tool_context.py",
    REPO_ROOT / "products" / "billing" / "src",
    REPO_ROOT / "products" / "payments" / "src",
    REPO_ROOT / "products" / "paywall" / "src",
]

# Variable-name substrings that strongly imply money context. Matching
# is case-insensitive and substring, so ``amount``, ``tool_cost`` and
# ``new_balance`` all trigger.
_MONEY_TOKENS = (
    "amount",
    "balance",
    "cost",
    "fee",
    "credit",
    "price",
    "spend",
    "cap",
    "deposit",
    "refund",
    "capture",
    "payout",
    "debit",
    "wallet",
)

# Allow-comment that silences a specific line. Kept verbose on purpose
# so grep will find it.
_ALLOW_COMMENT = "lint-no-float-money: allow"


@dataclass
class Violation:
    path: Path
    line: int
    snippet: str
    reason: str


def _is_money_name(name: str) -> bool:
    lowered = name.lower()
    return any(tok in lowered for tok in _MONEY_TOKENS)


def _name_of_target(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Subscript):
        return _name_of_target(target.value)
    return None


class _FloatCallVisitor(ast.NodeVisitor):
    """Collect every ``float(...)`` invocation with context."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str | None]] = []  # (lineno, nearest_var_name)
        self._context_stack: list[str] = []

    # Track assignment LHS as the nearest name context
    def visit_Assign(self, node: ast.Assign) -> None:
        names = [n for n in (_name_of_target(t) for t in node.targets) if n]
        self._context_stack.append(names[0] if names else "")
        self.generic_visit(node)
        self._context_stack.pop()

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        name = _name_of_target(node.target) or ""
        self._context_stack.append(name)
        self.generic_visit(node)
        self._context_stack.pop()

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        name = _name_of_target(node.target) or ""
        self._context_stack.append(name)
        self.generic_visit(node)
        self._context_stack.pop()

    def visit_Compare(self, node: ast.Compare) -> None:
        # left op right — walk both sides for float() calls
        name = _name_of_target(node.left) or ""
        self._context_stack.append(name)
        self.generic_visit(node)
        self._context_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        # Is this a ``float(x)`` call?
        is_float = isinstance(node.func, ast.Name) and node.func.id == "float" and len(node.args) == 1
        if is_float:
            ctx = self._context_stack[-1] if self._context_stack else None
            # Also look at the float() argument expression for a name
            arg_name: str | None = None
            arg = node.args[0]
            if isinstance(arg, ast.Name):
                arg_name = arg.id
            elif isinstance(arg, ast.Attribute):
                arg_name = arg.attr
            candidate = ctx or arg_name
            self.calls.append((node.lineno, candidate))
        self.generic_visit(node)


def find_violations(path: Path) -> list[Violation]:
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    lines = source.splitlines()
    visitor = _FloatCallVisitor()
    visitor.visit(tree)

    violations: list[Violation] = []
    for lineno, candidate in visitor.calls:
        idx = lineno - 1
        if idx < 0 or idx >= len(lines):
            continue
        line = lines[idx]
        prev_line = lines[idx - 1] if idx - 1 >= 0 else ""
        if _ALLOW_COMMENT in line or _ALLOW_COMMENT in prev_line:
            continue
        if candidate and _is_money_name(candidate):
            violations.append(
                Violation(
                    path=path,
                    line=lineno,
                    snippet=line.strip(),
                    reason=(
                        f"float() on money-context variable "
                        f"{candidate!r}. Use Decimal, or add "
                        f"`# {_ALLOW_COMMENT}` if this is observability."
                    ),
                )
            )
    return violations


def scan_paths(paths: list[Path]) -> list[Violation]:
    out: list[Violation] = []
    for p in paths:
        if p.is_file() and p.suffix == ".py":
            out.extend(find_violations(p))
        elif p.is_dir():
            for f in sorted(p.rglob("*.py")):
                out.extend(find_violations(f))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint: ``float(...)`` is forbidden on money-context variables.")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan (default: gateway + products money paths)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    scan = args.paths or DEFAULT_SCAN_PATHS
    if not args.quiet:
        for p in scan:
            print(f"Scanning: {p}")

    violations = scan_paths(scan)
    if not violations:
        if not args.quiet:
            print("  OK — no violations.")
        return 0

    print(f"\nFound {len(violations)} float-money violation(s):", file=sys.stderr)
    for v in violations:
        try:
            rel = v.path.relative_to(REPO_ROOT)
        except ValueError:
            rel = v.path
        print(f"  {rel}:{v.line}  {v.snippet}", file=sys.stderr)
        print(f"      → {v.reason}", file=sys.stderr)
    print(
        "\nFix: convert to Decimal at the boundary, or mark the line with "
        f"`# {_ALLOW_COMMENT}` if it's an observability exposition path.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
