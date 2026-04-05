"""Tests for scripts/update_website_stats.py.

Verifies that catalog.json stats are extracted correctly and HTML
marker-based substitution is idempotent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import update_website_stats as mod  # noqa: E402

# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------


def test_compute_stats_counts_total_and_services(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            [
                {"name": "a", "service": "billing"},
                {"name": "b", "service": "billing"},
                {"name": "c", "service": "payments"},
            ]
        )
    )
    stats = mod.compute_stats(catalog)
    assert stats.total_tools == 3
    assert stats.num_services == 2
    assert stats.per_service == {"billing": 2, "payments": 1}


def test_compute_stats_from_real_catalog() -> None:
    real = Path(__file__).parent.parent.parent / "gateway" / "src" / "catalog.json"
    stats = mod.compute_stats(real)
    assert stats.total_tools > 100
    assert stats.num_services >= 10
    assert "billing" in stats.per_service
    assert "payments" in stats.per_service


# ---------------------------------------------------------------------------
# replace_marker
# ---------------------------------------------------------------------------


def test_replace_marker_substitutes_single_occurrence() -> None:
    html = "Tools: <!-- a2a:stats:total-tools -->125<!-- /a2a:stats -->, done."
    out = mod.replace_marker(html, "total-tools", "128")
    assert "128" in out
    assert "125" not in out
    assert "<!-- a2a:stats:total-tools -->128<!-- /a2a:stats -->" in out


def test_replace_marker_is_idempotent() -> None:
    html = "x <!-- a2a:stats:num-services -->15<!-- /a2a:stats --> y"
    once = mod.replace_marker(html, "num-services", "15")
    twice = mod.replace_marker(once, "num-services", "15")
    assert once == twice


def test_replace_marker_missing_marker_leaves_text_unchanged() -> None:
    html = "no markers here"
    out = mod.replace_marker(html, "total-tools", "999")
    assert out == html


def test_replace_marker_replaces_all_occurrences() -> None:
    html = (
        "a <!-- a2a:stats:total-tools -->125<!-- /a2a:stats --> "
        "b <!-- a2a:stats:total-tools -->125<!-- /a2a:stats --> c"
    )
    out = mod.replace_marker(html, "total-tools", "128")
    assert out.count("128") == 2
    assert "125" not in out


# ---------------------------------------------------------------------------
# update_html_file
# ---------------------------------------------------------------------------


def _make_html(total: str = "125", services: str = "15") -> str:
    return (
        f"Live. <!-- a2a:stats:total-tools -->{total}<!-- /a2a:stats --> tools, "
        f"<!-- a2a:stats:num-services -->{services}<!-- /a2a:stats --> services."
    )


def test_update_html_file_write_mode_updates_both_markers(tmp_path: Path) -> None:
    f = tmp_path / "index.html"
    f.write_text(_make_html("125", "15"))
    stats = mod.Stats(total_tools=128, num_services=15, per_service={})
    changed = mod.update_html_file(f, stats, write=True)
    assert changed is True
    body = f.read_text()
    assert "128" in body
    assert "125" not in body


def test_update_html_file_check_mode_reports_drift(tmp_path: Path) -> None:
    f = tmp_path / "index.html"
    f.write_text(_make_html("125", "15"))
    stats = mod.Stats(total_tools=128, num_services=15, per_service={})
    changed = mod.update_html_file(f, stats, write=False)
    # check mode detects drift without writing
    assert changed is True
    assert "125" in f.read_text()  # file untouched


def test_update_html_file_check_mode_no_drift(tmp_path: Path) -> None:
    f = tmp_path / "index.html"
    f.write_text(_make_html("128", "15"))
    stats = mod.Stats(total_tools=128, num_services=15, per_service={})
    changed = mod.update_html_file(f, stats, write=False)
    assert changed is False


def test_update_html_file_missing_file_raises(tmp_path: Path) -> None:
    stats = mod.Stats(total_tools=128, num_services=15, per_service={})
    with pytest.raises(FileNotFoundError):
        mod.update_html_file(tmp_path / "missing.html", stats, write=False)
