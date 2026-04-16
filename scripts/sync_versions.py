#!/usr/bin/env python3
"""Single source of truth for the A2A release version.

The repo root contains a ``VERSION`` file holding one line with the
current release version, e.g. ``1.2.9``. This script propagates that
value into the four places ``publish.sh`` verifies before tagging:

    gateway/src/_version.py      __version__ = "x.y.z"
    sdk/pyproject.toml           version = "x.y.z"  (under [project])
    sdk-ts/package.json          "version": "x.y.z"
    SKILL.md                     version: x.y.z     (YAML frontmatter)

Usage:
    # CI guard — exit 1 if any target drifts from VERSION
    python scripts/sync_versions.py --check

    # Called by release.sh to bump everything at once
    python scripts/sync_versions.py --write

    # Override the VERSION file contents before sync (release.sh flow)
    python scripts/sync_versions.py --set 1.2.9 --write

Exit codes:
    0  in sync (check mode) or sync succeeded (write mode)
    1  drift detected (check mode only)
    2  invalid invocation or missing inputs
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VERSION_FILE = REPO_ROOT / "VERSION"

# Semantic version, optionally with a prerelease tag (1.2.9, 1.2.9-rc1).
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[A-Za-z0-9.\-]+)?$")


@dataclass
class SyncResult:
    version: str
    changed_files: list[Path] = field(default_factory=list)


# ---------------------------------------------------------------------------
# VERSION file
# ---------------------------------------------------------------------------


def read_version_file(path: Path) -> str:
    """Read and validate the top-level VERSION file."""
    text = path.read_text().strip()
    if not text:
        raise ValueError(f"VERSION file is empty: {path}")
    if not _SEMVER_RE.match(text):
        raise ValueError(f"VERSION file has invalid format: {text!r} (expected x.y.z or x.y.z-tag)")
    return text


def write_version_file(path: Path, version: str) -> None:
    """Overwrite the VERSION file with a new release version."""
    if not _SEMVER_RE.match(version):
        raise ValueError(f"Invalid version format: {version!r}")
    path.write_text(version + "\n")


# ---------------------------------------------------------------------------
# Target 1: gateway/src/_version.py
# ---------------------------------------------------------------------------


_GATEWAY_VERSION_RE = re.compile(r'(__version__\s*=\s*["\'])([^"\']+)(["\'])')


def update_gateway_version(path: Path, version: str, *, write: bool) -> bool:
    """Rewrite ``__version__`` in a Python module file.

    Returns True when the file is out of sync (and was rewritten in
    write mode). Returns False if it was already at ``version``.
    """
    original = path.read_text()
    updated, n = _GATEWAY_VERSION_RE.subn(
        rf"\g<1>{version}\g<3>",
        original,
        count=1,
    )
    if n == 0:
        raise ValueError(f"No __version__ assignment found in {path}")
    if updated == original:
        return False
    if write:
        path.write_text(updated)
    return True


# ---------------------------------------------------------------------------
# Target 2: sdk/pyproject.toml (or any other [project] pyproject)
# ---------------------------------------------------------------------------


# Matches the FIRST `version = "…"` assignment in the file. By
# convention that is always under [project]; test
# test_update_pyproject_version_only_touches_project_table pins this.
_PYPROJECT_VERSION_RE = re.compile(
    r'^(version\s*=\s*")([^"]+)(")',
    re.MULTILINE,
)


def update_pyproject_version(path: Path, version: str, *, write: bool) -> bool:
    """Rewrite the first ``version = "…"`` in a pyproject.toml file."""
    original = path.read_text()
    updated, n = _PYPROJECT_VERSION_RE.subn(
        rf"\g<1>{version}\g<3>",
        original,
        count=1,
    )
    if n == 0:
        raise ValueError(f"No version assignment found in {path}")
    if updated == original:
        return False
    if write:
        path.write_text(updated)
    return True


# ---------------------------------------------------------------------------
# Target 3: sdk-ts/package.json
# ---------------------------------------------------------------------------


def update_package_json_version(path: Path, version: str, *, write: bool) -> bool:
    """Rewrite the ``version`` key in a package.json, preserving field order."""
    original = path.read_text()
    data = json.loads(original)
    if data.get("version") == version:
        return False
    data["version"] = version
    if write:
        # 2-space indent matches npm's own formatter; trailing newline
        # matches what ``npm version`` writes.
        # ensure_ascii=False preserves unicode (em-dashes etc.) so we don't
        # escape characters that were literal in the original file.
        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        path.write_text(new_text)
    return True


# ---------------------------------------------------------------------------
# Target 4: SKILL.md (YAML frontmatter)
# ---------------------------------------------------------------------------


_SKILL_VERSION_RE = re.compile(r"^(version:\s*)(\S+)", re.MULTILINE)


def update_skill_version(path: Path, version: str, *, write: bool) -> bool:
    """Rewrite the ``version:`` field in a YAML frontmatter block."""
    original = path.read_text()
    updated, n = _SKILL_VERSION_RE.subn(rf"\g<1>{version}", original, count=1)
    if n == 0:
        raise ValueError(f"No version: field found in {path}")
    if updated == original:
        return False
    if write:
        path.write_text(updated)
    return True


# ---------------------------------------------------------------------------
# sync_all — bundle of all four
# ---------------------------------------------------------------------------


def _targets(root: Path) -> list[tuple[Path, callable]]:  # type: ignore[type-arg]
    return [
        (root / "gateway" / "src" / "_version.py", update_gateway_version),
        (root / "sdk" / "pyproject.toml", update_pyproject_version),
        (root / "sdk-ts" / "package.json", update_package_json_version),
        (root / "SKILL.md", update_skill_version),
    ]


def sync_all(root: Path, *, write: bool, override: str | None = None) -> SyncResult:
    """Sync every target file to the VERSION (or ``override``) value.

    Returns a SyncResult with the authoritative version and the list
    of files that needed changes. In check mode nothing is written;
    in write mode the files are rewritten.
    """
    version_file = root / "VERSION"
    if override is not None:
        if write:
            write_version_file(version_file, override)
        version = override
    else:
        if not version_file.exists():
            raise FileNotFoundError(f"VERSION file not found at {version_file}")
        version = read_version_file(version_file)

    changed: list[Path] = []
    for path, updater in _targets(root):
        if not path.exists():
            continue
        if updater(path, version, write=write):
            changed.append(path)
    return SyncResult(version=version, changed_files=changed)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync release version across monorepo")
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repo root (default: detected from script location)",
    )
    parser.add_argument(
        "--set",
        dest="override",
        default=None,
        help="Write this version to VERSION file before syncing (release.sh flow)",
    )
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--write", action="store_true", help="Update files in place")
    grp.add_argument("--check", action="store_true", help="Fail if drift detected")
    args = parser.parse_args(argv)

    try:
        result = sync_all(args.root, write=args.write, override=args.override)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print(f"VERSION: {result.version}")
    if not result.changed_files:
        print("  All targets in sync.")
        return 0

    verb = "UPDATED" if args.write else "OUT OF SYNC"
    for path in result.changed_files:
        try:
            display = path.relative_to(args.root)
        except ValueError:
            display = path
        print(f"  {verb}: {display}")

    if args.check:
        print(
            "\nVersion drift detected. Run: python scripts/sync_versions.py --write",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
