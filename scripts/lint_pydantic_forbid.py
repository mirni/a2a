#!/usr/bin/env python3
"""Lint: every Pydantic request model must set `extra="forbid"`.

The v1.2.3–v1.2.7 external audits repeatedly flagged "extra fields
accepted on request body" as a finding. Every request model in
gateway/src/routes/ already declares

    model_config = ConfigDict(extra="forbid")

today, but there is no structural enforcement stopping a future
contributor from dropping it and re-introducing the bug class. This
script is the enforcer.

Rules:

1. Flag every direct subclass of `BaseModel` that:
   - has no `model_config` assignment, OR
   - has `model_config = ConfigDict(extra="allow")` or "ignore".
2. Response models are exempt — class names ending in `Response`,
   `Envelope`, `Error`, `Info`, `Stats`, `Status` (configurable).
3. A subclass of another Pydantic model that already has `extra="forbid"`
   is NOT flagged — inheritance carries the config.
4. Non-Pydantic classes are ignored.

Usage:
    python scripts/lint_pydantic_forbid.py            # default: scan routes/
    python scripts/lint_pydantic_forbid.py path/to/file.py path/to/dir/
    python scripts/lint_pydantic_forbid.py --quiet    # suppress per-file logs

Exit codes:
    0  no violations
    1  one or more violations (CI should fail the build)
    2  invalid invocation
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCAN_PATHS = [REPO_ROOT / "gateway" / "src" / "routes"]

# Class-name suffixes that are NOT request models and therefore don't
# need `extra="forbid"`. Keep this list tight — if in doubt, add the
# `extra="forbid"` declaration rather than expanding exemptions.
_RESPONSE_SUFFIXES = (
    "Response",
    "Envelope",
    "Error",
    "Info",
    "Stats",
    "Status",
    "Result",
    "Summary",
)


@dataclass
class Violation:
    path: Path
    line: int
    class_name: str
    reason: str


# ---------------------------------------------------------------------------
# AST walking
# ---------------------------------------------------------------------------


def _is_basemodel_base(base: ast.expr) -> bool:
    """Is this base class `BaseModel` or `pydantic.BaseModel`?"""
    if isinstance(base, ast.Name) and base.id == "BaseModel":
        return True
    if (
        isinstance(base, ast.Attribute)
        and base.attr == "BaseModel"
        and isinstance(base.value, ast.Name)
        and base.value.id == "pydantic"
    ):
        return True
    return False


def _model_config_extra(cls: ast.ClassDef) -> str | None:
    """Return the `extra="..."` value from a `model_config = ConfigDict(...)`
    assignment inside the class body, or None if there is no such assignment.
    """
    for stmt in cls.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "model_config"):
            continue

        # model_config = ConfigDict(extra="forbid", ...)
        value = stmt.value
        if isinstance(value, ast.Call):
            for kw in value.keywords:
                if kw.arg == "extra" and isinstance(kw.value, ast.Constant):
                    return str(kw.value.value)
            # ConfigDict(...) with no extra keyword — explicit absence
            return "__missing__"

        # model_config = {"extra": "forbid"}
        if isinstance(value, ast.Dict):
            for k, v in zip(value.keys, value.values, strict=False):
                if isinstance(k, ast.Constant) and k.value == "extra" and isinstance(v, ast.Constant):
                    return str(v.value)
            return "__missing__"

        # model_config = SOMETHING_ELSE — can't tell, treat as missing
        return "__missing__"
    return None


def _is_response_model_name(name: str) -> bool:
    return any(name.endswith(suffix) for suffix in _RESPONSE_SUFFIXES)


def _collect_forbid_parents(tree: ast.Module) -> set[str]:
    """Names of classes in this module that already declare extra='forbid'.

    A subclass that inherits from one of these does NOT need its own
    declaration (Pydantic propagates model_config).
    """
    ok: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        extra = _model_config_extra(node)
        if extra == "forbid":
            ok.add(node.name)
    return ok


def find_violations(path: Path) -> list[Violation]:
    """Return all violations in a single .py file."""
    try:
        source = path.read_text()
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    forbid_parents = _collect_forbid_parents(tree)
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        # Skip response-model naming
        if _is_response_model_name(node.name):
            continue

        # Must be a direct BaseModel subclass OR inherit from a
        # forbid-configured class in the same module.
        is_basemodel_child = any(_is_basemodel_base(b) for b in node.bases)
        inherits_forbid_in_module = any(isinstance(b, ast.Name) and b.id in forbid_parents for b in node.bases)
        if not (is_basemodel_child or inherits_forbid_in_module):
            continue

        # If the class inherits from a module-local forbid parent and
        # doesn't override model_config, it's fine.
        extra = _model_config_extra(node)

        if inherits_forbid_in_module and extra is None:
            continue

        if extra == "forbid":
            continue

        if extra is None:
            reason = "missing model_config"
        elif extra == "__missing__":
            reason = "model_config without extra=..."
        else:
            reason = f'extra="{extra}"'

        violations.append(
            Violation(
                path=path,
                line=node.lineno,
                class_name=node.name,
                reason=reason,
            )
        )
    return violations


# ---------------------------------------------------------------------------
# Directory walking
# ---------------------------------------------------------------------------


def scan_paths(paths: list[Path]) -> list[Violation]:
    """Scan a mix of files and directories; return all violations."""
    out: list[Violation] = []
    for p in paths:
        if p.is_file():
            if p.suffix == ".py":
                out.extend(find_violations(p))
        elif p.is_dir():
            for f in sorted(p.rglob("*.py")):
                out.extend(find_violations(f))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint: Pydantic request models must set extra='forbid'")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Files or directories to scan (default: gateway/src/routes/)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-scan logs; only print violations",
    )
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

    print(
        f"\nFound {len(violations)} Pydantic request-model violation(s):",
        file=sys.stderr,
    )
    for v in violations:
        try:
            rel = v.path.relative_to(REPO_ROOT)
        except ValueError:
            rel = v.path
        print(
            f"  {rel}:{v.line}  class {v.class_name}  — {v.reason}",
            file=sys.stderr,
        )
    print(
        '\nFix: add `model_config = ConfigDict(extra="forbid")` to the class.',
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
