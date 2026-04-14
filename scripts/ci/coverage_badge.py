#!/usr/bin/env python3
"""Generate a shields.io endpoint badge JSON from Cobertura XML coverage reports.

Usage:
    python scripts/ci/coverage_badge.py coverage-*.xml -o badge.json

Output is a shields.io endpoint JSON:
    {"schemaVersion": 1, "label": "coverage", "message": "94.3%", "color": "brightgreen"}
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _color_for(pct: float) -> str:
    """Return a shields.io color based on coverage percentage."""
    if pct >= 90:
        return "brightgreen"
    if pct >= 80:
        return "green"
    if pct >= 70:
        return "yellowgreen"
    if pct >= 60:
        return "yellow"
    if pct >= 50:
        return "orange"
    return "red"


def main() -> int:
    output = "coverage-badge.json"
    xml_files: list[str] = []

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            output = args[i + 1]
            i += 2
        else:
            if Path(args[i]).exists():
                xml_files.append(args[i])
            i += 1

    if not xml_files:
        print("No coverage XML files found.", file=sys.stderr)
        return 1

    total_lines = 0
    total_hits = 0

    for xml_path in xml_files:
        tree = ET.parse(xml_path)  # noqa: S314  # nosemgrep: use-defused-xml-parse  — trusted CI-generated XML
        root = tree.getroot()
        lines_valid = int(root.get("lines-valid", "0"))
        lines_covered = int(root.get("lines-covered", "0"))
        if lines_valid > 0:
            total_lines += lines_valid
            total_hits += lines_covered
        else:
            # Fallback: count lines from packages
            for pkg in root.findall(".//package"):
                for cls in pkg.findall("classes/class"):
                    n = len(cls.findall("lines/line"))
                    h = sum(1 for ln in cls.findall("lines/line") if int(ln.get("hits", "0")) > 0)
                    total_lines += n
                    total_hits += h

    pct = round(total_hits / total_lines * 100, 1) if total_lines else 0

    badge = {
        "schemaVersion": 1,
        "label": "coverage",
        "message": f"{pct}%",
        "color": _color_for(pct),
    }

    Path(output).write_text(json.dumps(badge, indent=2) + "\n")
    print(f"Badge: {pct}% ({_color_for(pct)}) → {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
