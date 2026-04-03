"""Tests for coverage_ratchet.py --markdown flag."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest
from coverage_ratchet import _generate_markdown, cmd_check


@pytest.fixture()
def baseline_file(tmp_path: Path) -> Path:
    """Create a temporary baseline file."""
    bf = tmp_path / ".coverage-baseline.json"
    bf.write_text(
        json.dumps(
            {
                "billing": 84.0,
                "gateway": 94.0,
                "identity": 96.0,
            },
            sort_keys=True,
        )
    )
    return bf


@pytest.fixture()
def _coverage_xmls(tmp_path: Path) -> list[str]:
    """Create minimal Cobertura XML files."""
    files = []
    for name, rate in [("billing", 0.85), ("gateway", 0.94), ("identity", 0.93)]:
        xml = tmp_path / f"coverage-{name}.xml"
        xml.write_text(
            f'<?xml version="1.0"?>'
            f'<coverage line-rate="{rate}"></coverage>'
        )
        files.append(str(xml))
    return files


class TestGenerateMarkdown:
    """Tests for the _generate_markdown helper."""

    def test_produces_table_with_all_modules(self) -> None:
        rows = [
            {"module": "billing", "baseline": 84.0, "current": 85.0, "delta": 1.0, "status": "+1.0%"},
            {"module": "gateway", "baseline": 94.0, "current": 94.0, "delta": 0.0, "status": "OK"},
        ]
        md = _generate_markdown(rows, passed=True)
        assert "| Module" in md
        assert "| billing" in md
        assert "| gateway" in md
        assert "passed" in md.lower()

    def test_fail_summary(self) -> None:
        rows = [
            {"module": "identity", "baseline": 96.0, "current": 93.0, "delta": -3.0, "status": "FAIL"},
        ]
        md = _generate_markdown(rows, passed=False)
        assert "failed" in md.lower()
        assert "identity" in md

    def test_marker_comment_present(self) -> None:
        md = _generate_markdown([], passed=True)
        assert "<!-- coverage-ratchet -->" in md

    def test_skip_and_new_rows(self) -> None:
        rows = [
            {"module": "old", "baseline": 80.0, "current": None, "delta": None, "status": "SKIP"},
            {"module": "new", "baseline": None, "current": 75.0, "delta": None, "status": "NEW"},
        ]
        md = _generate_markdown(rows, passed=True)
        assert "SKIP" in md
        assert "NEW" in md


class TestCmdCheckMarkdown:
    """Tests for cmd_check with --markdown output."""

    def test_writes_markdown_file(
        self, tmp_path: Path, baseline_file: Path, _coverage_xmls: list[str]
    ) -> None:
        md_path = tmp_path / "coverage-comment.md"
        with mock.patch("coverage_ratchet.BASELINE_FILE", baseline_file):
            cmd_check(_coverage_xmls, markdown_path=str(md_path))
        assert md_path.exists()
        content = md_path.read_text()
        assert "| Module" in content
        assert "billing" in content

    def test_no_file_when_no_markdown_path(
        self, tmp_path: Path, baseline_file: Path, _coverage_xmls: list[str]
    ) -> None:
        with mock.patch("coverage_ratchet.BASELINE_FILE", baseline_file):
            ret = cmd_check(_coverage_xmls, markdown_path=None)
        # Should still work normally
        assert ret in (0, 1)

    def test_fail_returns_1_with_markdown(
        self, tmp_path: Path, baseline_file: Path, _coverage_xmls: list[str]
    ) -> None:
        """Identity drops from 96 -> 93, should fail."""
        md_path = tmp_path / "coverage-comment.md"
        with mock.patch("coverage_ratchet.BASELINE_FILE", baseline_file):
            ret = cmd_check(_coverage_xmls, markdown_path=str(md_path))
        assert ret == 1
        content = md_path.read_text()
        assert "FAIL" in content
