"""Tests for scripts/sync_versions.py.

Verifies that the top-level VERSION file is the single source of truth
for gateway/src/_version.py, sdk/pyproject.toml, and sdk-ts/package.json.

This is the drift guard that publish.sh relies on — these three files
MUST all agree on the same version string at the release commit, or
publish.sh refuses to tag.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import sync_versions as mod  # noqa: E402

# ---------------------------------------------------------------------------
# regression: package.json with unicode characters (em-dash) must not
# get ascii-escaped by the JSON writer.
# ---------------------------------------------------------------------------


def test_update_package_json_preserves_unicode_in_description(tmp_path: Path) -> None:
    """v1.2.9 regression: running sync against sdk-ts/package.json must
    not rewrite the em-dash (``—``) in the description as ``\\u2014``.
    ``json.dumps`` needs ``ensure_ascii=False``.
    """
    f = tmp_path / "package.json"
    original = '{\n  "name": "@greenhelix/sdk",\n  "version": "1.2.7",\n  "description": "A — B"\n}\n'
    f.write_text(original, encoding="utf-8")
    mod.update_package_json_version(f, "1.2.9", write=True)
    body = f.read_text(encoding="utf-8")
    assert '"version": "1.2.9"' in body
    assert "A — B" in body
    assert "\\u2014" not in body


# ---------------------------------------------------------------------------
# read_version_file
# ---------------------------------------------------------------------------


def test_read_version_file_strips_whitespace(tmp_path: Path) -> None:
    v = tmp_path / "VERSION"
    v.write_text("1.2.9\n")
    assert mod.read_version_file(v) == "1.2.9"


def test_read_version_file_rejects_empty(tmp_path: Path) -> None:
    v = tmp_path / "VERSION"
    v.write_text("")
    with pytest.raises(ValueError, match="empty"):
        mod.read_version_file(v)


def test_read_version_file_rejects_bad_format(tmp_path: Path) -> None:
    v = tmp_path / "VERSION"
    v.write_text("not-a-version")
    with pytest.raises(ValueError, match="format"):
        mod.read_version_file(v)


def test_read_version_file_accepts_semver_with_prerelease(tmp_path: Path) -> None:
    v = tmp_path / "VERSION"
    v.write_text("1.2.9-rc1\n")
    assert mod.read_version_file(v) == "1.2.9-rc1"


# ---------------------------------------------------------------------------
# update_gateway_version
# ---------------------------------------------------------------------------


def test_update_gateway_version_rewrites_python_module(tmp_path: Path) -> None:
    f = tmp_path / "_version.py"
    f.write_text('"""doc."""\n\n__version__ = "1.2.7"\n')
    changed = mod.update_gateway_version(f, "1.2.9", write=True)
    assert changed is True
    assert '__version__ = "1.2.9"' in f.read_text()
    assert '"""doc."""' in f.read_text()  # docstring preserved


def test_update_gateway_version_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "_version.py"
    f.write_text('__version__ = "1.2.9"\n')
    changed = mod.update_gateway_version(f, "1.2.9", write=True)
    assert changed is False


def test_update_gateway_version_check_mode_no_write(tmp_path: Path) -> None:
    f = tmp_path / "_version.py"
    f.write_text('__version__ = "1.2.7"\n')
    changed = mod.update_gateway_version(f, "1.2.9", write=False)
    assert changed is True
    assert "1.2.7" in f.read_text()  # file untouched


# ---------------------------------------------------------------------------
# update_pyproject_version
# ---------------------------------------------------------------------------


def test_update_pyproject_version_rewrites_toml(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text('[project]\nname = "foo"\nversion = "1.2.7"\ndescription = "bar"\n')
    changed = mod.update_pyproject_version(f, "1.2.9", write=True)
    assert changed is True
    body = f.read_text()
    assert 'version = "1.2.9"' in body
    assert 'name = "foo"' in body
    assert 'description = "bar"' in body


def test_update_pyproject_version_only_touches_project_table(tmp_path: Path) -> None:
    """Must not rewrite a `version = ` line in [tool.poetry] or similar."""
    f = tmp_path / "pyproject.toml"
    f.write_text('[project]\nname = "foo"\nversion = "1.2.7"\n\n[tool.black]\nversion = "stable"\n')
    mod.update_pyproject_version(f, "1.2.9", write=True)
    body = f.read_text()
    # Only first occurrence is rewritten (under [project]).
    assert body.count('version = "1.2.9"') == 1
    assert '"stable"' in body


def test_update_pyproject_version_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "pyproject.toml"
    f.write_text('[project]\nversion = "1.2.9"\n')
    changed = mod.update_pyproject_version(f, "1.2.9", write=True)
    assert changed is False


# ---------------------------------------------------------------------------
# update_package_json_version
# ---------------------------------------------------------------------------


def test_update_package_json_version_preserves_field_order(tmp_path: Path) -> None:
    f = tmp_path / "package.json"
    original = {
        "name": "@greenhelix/a2a-sdk",
        "version": "1.2.7",
        "description": "TS SDK",
        "dependencies": {"axios": "^1.6.0"},
    }
    f.write_text(json.dumps(original, indent=2) + "\n")
    changed = mod.update_package_json_version(f, "1.2.9", write=True)
    assert changed is True
    updated = json.loads(f.read_text())
    assert updated["version"] == "1.2.9"
    assert updated["name"] == "@greenhelix/a2a-sdk"
    assert updated["dependencies"] == {"axios": "^1.6.0"}
    # field order preserved (name before version)
    keys = list(updated.keys())
    assert keys.index("name") < keys.index("version")


def test_update_package_json_version_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "package.json"
    f.write_text(json.dumps({"name": "x", "version": "1.2.9"}, indent=2) + "\n")
    changed = mod.update_package_json_version(f, "1.2.9", write=True)
    assert changed is False


def test_update_package_json_version_trailing_newline_preserved(tmp_path: Path) -> None:
    f = tmp_path / "package.json"
    f.write_text(json.dumps({"version": "1.2.7"}, indent=2) + "\n")
    mod.update_package_json_version(f, "1.2.9", write=True)
    assert f.read_text().endswith("\n")


# ---------------------------------------------------------------------------
# sync_all
# ---------------------------------------------------------------------------


def _make_tree(root: Path, version: str) -> None:
    """Create a miniature repo layout matching /workdir."""
    (root / "VERSION").write_text(version + "\n")
    (root / "gateway" / "src").mkdir(parents=True)
    (root / "gateway" / "src" / "_version.py").write_text('"""gateway version."""\n\n__version__ = "0.0.0"\n')
    (root / "sdk").mkdir()
    (root / "sdk" / "pyproject.toml").write_text('[project]\nname = "a2a"\nversion = "0.0.0"\n')
    (root / "sdk-ts").mkdir()
    (root / "sdk-ts" / "package.json").write_text(
        json.dumps({"name": "@greenhelix/a2a-sdk", "version": "0.0.0"}, indent=2) + "\n"
    )


def test_sync_all_writes_every_target(tmp_path: Path) -> None:
    _make_tree(tmp_path, "1.2.9")
    result = mod.sync_all(tmp_path, write=True)
    assert result.version == "1.2.9"
    assert result.changed_files == [
        tmp_path / "gateway" / "src" / "_version.py",
        tmp_path / "sdk" / "pyproject.toml",
        tmp_path / "sdk-ts" / "package.json",
    ]
    # verify every target now reports 1.2.9
    assert '__version__ = "1.2.9"' in (tmp_path / "gateway" / "src" / "_version.py").read_text()
    assert 'version = "1.2.9"' in (tmp_path / "sdk" / "pyproject.toml").read_text()
    assert json.loads((tmp_path / "sdk-ts" / "package.json").read_text())["version"] == "1.2.9"


def test_sync_all_check_mode_reports_drift_without_writing(tmp_path: Path) -> None:
    _make_tree(tmp_path, "1.2.9")
    result = mod.sync_all(tmp_path, write=False)
    assert len(result.changed_files) == 3
    # Nothing written
    assert '"0.0.0"' in (tmp_path / "gateway" / "src" / "_version.py").read_text()


def test_sync_all_no_drift_returns_empty(tmp_path: Path) -> None:
    _make_tree(tmp_path, "1.2.9")
    mod.sync_all(tmp_path, write=True)  # first pass
    result = mod.sync_all(tmp_path, write=True)  # second pass
    assert result.changed_files == []


def test_sync_all_missing_version_file_raises(tmp_path: Path) -> None:
    (tmp_path / "gateway" / "src").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="VERSION"):
        mod.sync_all(tmp_path, write=False)


# ---------------------------------------------------------------------------
# real-repo invariant: the tracked VERSION file matches the three targets
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).parent.parent.parent


def test_real_repo_version_file_exists_and_is_semver() -> None:
    """The VERSION file must be committed, readable, and parseable."""
    vf = REPO_ROOT / "VERSION"
    if not vf.exists():
        pytest.skip("VERSION file not created yet (test runs after P0-3 commits).")
    v = mod.read_version_file(vf)
    # semver with optional prerelease
    import re

    assert re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$", v), f"VERSION file contains invalid semver: {v!r}"


def test_real_repo_targets_in_sync_with_version_file() -> None:
    """gateway/_version.py, sdk/pyproject.toml, sdk-ts/package.json must
    all match the VERSION file. This is the guardrail that prevents
    publish.sh from failing in CI."""
    vf = REPO_ROOT / "VERSION"
    if not vf.exists():
        pytest.skip("VERSION file not created yet (test runs after P0-3 commits).")
    result = mod.sync_all(REPO_ROOT, write=False)
    assert result.changed_files == [], (
        f"Version drift detected — run scripts/sync_versions.py --write\n"
        f"Target VERSION: {result.version}\n"
        f"Out-of-sync: {[str(p.relative_to(REPO_ROOT)) for p in result.changed_files]}"
    )
