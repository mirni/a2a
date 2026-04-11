#!/usr/bin/env python3
"""Keep website/*.html stats in sync with gateway/src/catalog.json.

The website homepage and docs page advertise totals like "128 tools, 15 services".
Rather than hand-editing these numbers with every release, this script reads the
authoritative catalog.json and rewrites values inside HTML marker comments:

    <!-- a2a:stats:total-tools -->128<!-- /a2a:stats -->
    <!-- a2a:stats:num-services -->15<!-- /a2a:stats -->
    <!-- a2a:stats:version -->0.9.6<!-- /a2a:stats -->

Usage:
    # Update in place (for deploy / pre-commit hook):
    python scripts/update_website_stats.py --write

    # Check only (for CI); exits 1 if drift detected:
    python scripts/update_website_stats.py --check

Exit codes:
    0 - in sync (or --write succeeded)
    1 - drift detected (--check only)
    2 - invalid invocation or missing inputs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = REPO_ROOT / "gateway" / "src" / "catalog.json"
DEFAULT_VERSION_FILE = REPO_ROOT / "gateway" / "src" / "_version.py"
DEFAULT_HTML_FILES = [
    REPO_ROOT / "website" / "index.html",
    REPO_ROOT / "website" / "docs.html",
]


@dataclass
class Stats:
    total_tools: int
    num_services: int
    per_service: dict[str, int] = field(default_factory=dict)
    version: str = ""


def compute_stats(catalog_path: Path) -> Stats:
    """Load catalog.json and return aggregate counts."""
    data = json.loads(catalog_path.read_text())
    if not isinstance(data, list):
        raise ValueError(f"Expected list at {catalog_path}, got {type(data).__name__}")

    per_service: dict[str, int] = {}
    for tool in data:
        svc = tool.get("service", "unknown")
        per_service[svc] = per_service.get(svc, 0) + 1

    return Stats(
        total_tools=len(data),
        num_services=len(per_service),
        per_service=per_service,
    )


def read_version(version_file: Path) -> str:
    """Extract __version__ value from a _version.py file."""
    if not version_file.exists():
        return ""
    text = version_file.read_text()
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else ""


def replace_marker(html: str, marker: str, new_value: str) -> str:
    """Replace content between <!-- a2a:stats:KEY --> and <!-- /a2a:stats --> markers.

    Idempotent: calling twice with the same value produces identical output.
    Missing markers are left unchanged (no error).
    """
    pattern = re.compile(
        r"(<!--\s*a2a:stats:" + re.escape(marker) + r"\s*-->)"
        r"([^<]*)"
        r"(<!--\s*/a2a:stats\s*-->)"
    )
    return pattern.sub(rf"\g<1>{new_value}\g<3>", html)


def update_html_file(path: Path, stats: Stats, *, write: bool) -> bool:
    """Apply stats to an HTML file.

    Returns True if the file needs updates (or was updated in write mode).
    Returns False if the file is already in sync.
    """
    if not path.exists():
        raise FileNotFoundError(f"HTML file not found: {path}")

    original = path.read_text()
    updated = original
    updated = replace_marker(updated, "total-tools", str(stats.total_tools))
    updated = replace_marker(updated, "num-services", str(stats.num_services))
    if stats.version:
        updated = replace_marker(updated, "version", stats.version)

    if updated == original:
        return False

    if write:
        path.write_text(updated)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync website stats from catalog.json")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--version-file", type=Path, default=DEFAULT_VERSION_FILE)
    parser.add_argument("--html", type=Path, nargs="+", default=DEFAULT_HTML_FILES)
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--write", action="store_true", help="Update files in place")
    grp.add_argument("--check", action="store_true", help="Fail if drift detected")
    args = parser.parse_args(argv)

    if not args.catalog.exists():
        print(f"ERROR: catalog not found: {args.catalog}", file=sys.stderr)
        return 2

    stats = compute_stats(args.catalog)
    stats.version = read_version(args.version_file)

    print(
        f"Catalog stats: {stats.total_tools} tools, {stats.num_services} services, version={stats.version or 'unknown'}"
    )

    drift = False
    for html_path in args.html:
        try:
            changed = update_html_file(html_path, stats, write=args.write)
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        # Pretty-print relative to REPO_ROOT when the HTML lives inside
        # the repo, fall back to the absolute path for staged copies
        # (scripts/create_package.sh substitutes into /tmp staging dirs).
        try:
            display = html_path.relative_to(REPO_ROOT)
        except ValueError:
            display = html_path
        if changed:
            drift = True
            verb = "UPDATED" if args.write else "OUT OF SYNC"
            print(f"  {verb}: {display}")
        else:
            print(f"  OK:      {display}")

    if args.check and drift:
        print(
            "\nWebsite stats drift detected. Run: python scripts/update_website_stats.py --write",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
