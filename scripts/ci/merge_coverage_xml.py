#!/usr/bin/env python3
"""Merge multiple Cobertura XML coverage reports into one.

Each shard XML covers a disjoint set of test files against the same source.
This script unions the ``<package>/<class>/<line>`` entries and recomputes
aggregate hit counts and line-rate attributes so the ratchet sees the full
picture.

Usage:
    python scripts/ci/merge_coverage_xml.py coverage-gateway-*.xml -o coverage-gateway.xml
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _merge(xml_paths: list[str]) -> ET.ElementTree:
    """Merge Cobertura XMLs by unioning line hits per file."""
    # file_path -> line_number -> total_hits
    file_lines: dict[str, dict[int, int]] = {}
    # file_path -> (class_name, class_filename, package_name)
    file_meta: dict[str, tuple[str, str, str]] = {}

    for xml_path in xml_paths:
        tree = ET.parse(xml_path)  # noqa: S314 — trusted CI-generated XML
        for pkg in tree.findall(".//package"):
            pkg_name = pkg.get("name", "")
            for cls in pkg.findall("classes/class"):
                fname = cls.get("filename", "")
                cname = cls.get("name", "")
                if fname not in file_meta:
                    file_meta[fname] = (cname, fname, pkg_name)
                if fname not in file_lines:
                    file_lines[fname] = {}
                for line in cls.findall("lines/line"):
                    num = int(line.get("number", "0"))
                    hits = int(line.get("hits", "0"))
                    file_lines[fname][num] = file_lines[fname].get(num, 0) + hits

    # Rebuild a single Cobertura XML
    total_lines = 0
    total_hits = 0

    root = ET.Element("coverage")
    packages_el = ET.SubElement(root, "packages")

    # Group files by package
    pkg_groups: dict[str, list[str]] = {}
    for fname, (_, _, pkg_name) in sorted(file_meta.items()):
        pkg_groups.setdefault(pkg_name, []).append(fname)

    for pkg_name, fnames in sorted(pkg_groups.items()):
        pkg_el = ET.SubElement(packages_el, "package", name=pkg_name)
        classes_el = ET.SubElement(pkg_el, "classes")
        pkg_lines = 0
        pkg_hits = 0

        for fname in sorted(fnames):
            cname, cfilename, _ = file_meta[fname]
            lines = file_lines.get(fname, {})
            n_lines = len(lines)
            n_hits = sum(1 for h in lines.values() if h > 0)
            rate = n_hits / n_lines if n_lines else 0

            cls_el = ET.SubElement(
                classes_el,
                "class",
                name=cname,
                filename=cfilename,
                complexity="0",
            )
            cls_el.set("line-rate", f"{rate:.4f}")
            cls_el.set("branch-rate", "0")
            lines_el = ET.SubElement(cls_el, "lines")
            for num in sorted(lines):
                ET.SubElement(lines_el, "line", number=str(num), hits=str(lines[num]))

            pkg_lines += n_lines
            pkg_hits += n_hits
            total_lines += n_lines
            total_hits += n_hits

        pkg_rate = pkg_hits / pkg_lines if pkg_lines else 0
        pkg_el.set("line-rate", f"{pkg_rate:.4f}")
        pkg_el.set("branch-rate", "0")
        pkg_el.set("complexity", "0")

    overall_rate = total_hits / total_lines if total_lines else 0
    root.set("line-rate", f"{overall_rate:.4f}")
    root.set("branch-rate", "0")
    root.set("lines-valid", str(total_lines))
    root.set("lines-covered", str(total_hits))
    root.set("version", "1")
    root.set("timestamp", "0")

    return ET.ElementTree(root)


def main() -> int:
    output = "merged-coverage.xml"
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
        print("No XML files found to merge.", file=sys.stderr)
        return 1

    print(f"Merging {len(xml_files)} coverage XMLs → {output}")
    for f in xml_files:
        print(f"  {f}")

    tree = _merge(xml_files)
    tree.write(output, xml_declaration=True, encoding="utf-8")

    rate = float(tree.getroot().get("line-rate", "0"))
    print(f"Merged line coverage: {rate * 100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
