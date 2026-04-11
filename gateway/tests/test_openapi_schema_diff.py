"""v1.2.4 audit P1 T-5: OpenAPI schema diff gate.

Dumps the current schema and compares it against
``reports/openapi-baseline.json``. Runs inside the ordinary
pytest job so the diff gate is enforced on every PR without
needing a separate CI workflow.

Failure modes
=============

* Baseline missing → skip with a loud message (fresh clone,
  first-time setup).
* Schema dump crashes → fail (something broke app wiring).
* Breaking diff with no authorisation → fail. The fail message
  includes the exact diff so the human can decide whether to
  update the baseline or revert the change.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_BASELINE = _REPO_ROOT / "reports" / "openapi-baseline.json"
_DUMP_SCRIPT = _REPO_ROOT / "scripts" / "dump_openapi.py"
_DIFF_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "diff_openapi.py"


@pytest.mark.skipif(not _BASELINE.exists(), reason="baseline not committed yet")
def test_openapi_schema_matches_baseline(tmp_path):
    """Current schema must not break the committed baseline.

    Additive changes (new routes, new optional fields) are
    permitted. Removals, type changes, and newly-required fields
    must be authorised by a ``deprecation:`` line in the PR body.
    """
    current = tmp_path / "current.json"
    dump = subprocess.run(  # noqa: S603 — sys.executable + pinned repo script
        [sys.executable, str(_DUMP_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(_REPO_ROOT),
        check=False,
    )
    assert dump.returncode == 0, f"dump_openapi failed: {dump.stderr}"
    current.write_text(dump.stdout, encoding="utf-8")

    # Sanity-check that the dump is parseable and non-trivial.
    parsed = json.loads(current.read_text(encoding="utf-8"))
    assert "paths" in parsed
    assert len(parsed["paths"]) > 10

    diff = subprocess.run(  # noqa: S603 — sys.executable + pinned repo script
        [
            sys.executable,
            str(_DIFF_SCRIPT),
            "--baseline",
            str(_BASELINE),
            "--current",
            str(current),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(_REPO_ROOT),
        check=False,
    )
    # Exit 0 = clean or additive; exit 1 = breaking without
    # deprecation authorisation; exit 2 = script error.
    assert diff.returncode != 2, f"diff_openapi error: {diff.stderr}"
    assert diff.returncode == 0, (
        f"OpenAPI schema diff has breaking changes:\n{diff.stdout}\n"
        f"If the change is intentional, either regenerate the "
        f"baseline (`python scripts/dump_openapi.py > "
        f"reports/openapi-baseline.json`) and include a "
        f"`deprecation:` line in the PR body, or revert the "
        f"breaking change."
    )
