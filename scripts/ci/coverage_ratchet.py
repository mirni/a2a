#!/usr/bin/env python3
"""Coverage ratchet: ensure test coverage never decreases.

Usage:
    # Check PR coverage against baseline (fails if any module decreased):
    python scripts/ci/coverage_ratchet.py check coverage-*.xml

    # Update baseline with current coverage (run on main after merge):
    python scripts/ci/coverage_ratchet.py update coverage-*.xml
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BASELINE_FILE = Path(__file__).resolve().parents[2] / ".coverage-baseline.json"

# Tolerance: coverage can drop by this much without failing (accounts for
# rounding / minor test changes).
TOLERANCE = 0.1  # percentage points


def _parse_coverage(xml_path: str) -> tuple[str, float]:
    """Extract module name and line coverage % from a Cobertura XML report."""
    tree = ET.parse(xml_path)  # noqa: S314  # nosemgrep: use-defused-xml-parse  — trusted CI-generated XML
    rate = float(tree.getroot().get("line-rate", "0"))
    pct = round(rate * 100, 2)
    # Module name from filename: coverage-gateway.xml -> gateway
    name = Path(xml_path).stem.replace("coverage-", "")
    return name, pct


def _load_baseline() -> dict[str, float]:
    """Load the coverage baseline from the repo."""
    if not BASELINE_FILE.exists():
        return {}
    return json.loads(BASELINE_FILE.read_text())


def _save_baseline(data: dict[str, float]) -> None:
    """Save the coverage baseline to the repo."""
    BASELINE_FILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _generate_markdown(rows: list[dict], *, passed: bool) -> str:
    """Generate a Markdown coverage report with a table and summary."""
    lines = ["<!-- coverage-ratchet -->", "## Coverage Ratchet Report", ""]
    lines.append("| Module | Baseline | Current | Delta | Status |")
    lines.append("|--------|----------|---------|-------|--------|")

    for r in rows:
        base = f"{r['baseline']:.1f}%" if r["baseline"] is not None else "N/A"
        curr = f"{r['current']:.1f}%" if r["current"] is not None else "N/A"
        delta = f"{r['delta']:+.1f}%" if r["delta"] is not None else "—"
        lines.append(f"| {r['module']} | {base} | {curr} | {delta} | {r['status']} |")

    total = [r for r in rows if r["current"] is not None and r["baseline"] is not None]
    if total:
        avg = sum(r["current"] for r in total) / len(total)
        lines.append("")
        lines.append(f"**{len(total)} modules** | average coverage: **{avg:.1f}%**")

    verdict = "passed" if passed else "FAILED"
    emoji = "white_check_mark" if passed else "x"
    lines.append("")
    lines.append(f":{emoji}: Coverage ratchet **{verdict}**.")
    lines.append("")
    return "\n".join(lines)


def cmd_check(xml_files: list[str], *, markdown_path: str | None = None) -> int:
    """Compare current coverage against baseline. Returns 0 on pass, 1 on fail."""
    baseline = _load_baseline()
    if not baseline:
        print("No coverage baseline found — skipping ratchet check.")
        return 0

    current: dict[str, float] = {}
    for f in xml_files:
        name, pct = _parse_coverage(f)
        current[name] = pct

    failed = False
    rows: list[dict] = []
    print(f"{'Module':<20} {'Baseline':>10} {'Current':>10} {'Delta':>10}  Status")
    print("-" * 65)

    for module in sorted(set(list(baseline.keys()) + list(current.keys()))):
        base_pct = baseline.get(module)
        curr_pct = current.get(module)

        if curr_pct is None:
            print(f"{module:<20} {base_pct:>9.1f}% {'N/A':>10}  {'SKIP':>10}")
            rows.append({"module": module, "baseline": base_pct, "current": None, "delta": None, "status": "SKIP"})
            continue
        if base_pct is None:
            print(f"{module:<20} {'N/A':>10} {curr_pct:>9.1f}%  {'NEW':>10}")
            rows.append({"module": module, "baseline": None, "current": curr_pct, "delta": None, "status": "NEW"})
            continue

        delta = curr_pct - base_pct
        status = "OK"
        if delta < -TOLERANCE:
            status = "FAIL"
            failed = True
        elif delta > 0:
            status = f"+{delta:.1f}%"

        print(f"{module:<20} {base_pct:>9.1f}% {curr_pct:>9.1f}% {delta:>+9.1f}%  {status}")
        rows.append({"module": module, "baseline": base_pct, "current": curr_pct, "delta": delta, "status": status})

    if failed:
        print("\nCoverage ratchet FAILED: one or more modules dropped below baseline.")
        print("Fix: add tests to restore coverage, or update baseline if decrease is intentional.")
    else:
        print("\nCoverage ratchet passed.")

    if markdown_path is not None:
        md = _generate_markdown(rows, passed=not failed)
        Path(markdown_path).write_text(md)

    return 1 if failed else 0


def cmd_update(xml_files: list[str]) -> int:
    """Update the baseline file with current coverage values."""
    baseline = _load_baseline()
    updated = False

    for f in xml_files:
        name, pct = _parse_coverage(f)
        old = baseline.get(name)
        if old is None or pct > old:
            baseline[name] = pct
            arrow = f" (was {old:.1f}%)" if old is not None else " (new)"
            print(f"  {name}: {pct:.1f}%{arrow}")
            updated = True
        else:
            print(f"  {name}: {pct:.1f}% (unchanged, baseline={old:.1f}%)")

    if updated:
        _save_baseline(baseline)
        print(f"\nBaseline updated: {BASELINE_FILE}")
    else:
        print("\nNo improvements — baseline unchanged.")
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "update"):
        print(__doc__)
        return 2

    cmd = sys.argv[1]
    markdown_path: str | None = None
    xml_files: list[str] = []

    for arg in sys.argv[2:]:
        if arg.startswith("--markdown="):
            markdown_path = arg.split("=", 1)[1]
        elif Path(arg).exists():
            xml_files.append(arg)

    if not xml_files:
        print("No coverage XML files found.")
        return 0

    if cmd == "check":
        return cmd_check(xml_files, markdown_path=markdown_path)
    return cmd_update(xml_files)


if __name__ == "__main__":
    sys.exit(main())
