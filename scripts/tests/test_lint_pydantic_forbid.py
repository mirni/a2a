"""Tests for scripts/lint_pydantic_forbid.py.

Guardrail: every Pydantic request model in gateway/src/routes/ must
declare `model_config = ConfigDict(extra="forbid")` (or equivalent).
The lint is a small AST walker — these tests cover the parsing and
the whole-file behaviour.

Background: the v1.2.3–v1.2.7 external audits kept flagging "extra
fields accepted on request body" findings. Every route model already
has `extra="forbid"` today but there is no structural check stopping
a future contributor from dropping it. This lint closes that gap.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import lint_pydantic_forbid as mod  # noqa: E402

# ---------------------------------------------------------------------------
# find_violations — single file AST walking
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


def test_model_with_forbid_config_passes(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "good.py",
        """from pydantic import BaseModel, ConfigDict

class GoodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
""",
    )
    assert mod.find_violations(f) == []


def test_model_missing_config_flagged(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "bad.py",
        """from pydantic import BaseModel

class BadRequest(BaseModel):
    name: str
""",
    )
    violations = mod.find_violations(f)
    assert len(violations) == 1
    v = violations[0]
    assert v.class_name == "BadRequest"
    assert v.reason == "missing model_config"


def test_model_with_allow_extras_flagged(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "bad_allow.py",
        """from pydantic import BaseModel, ConfigDict

class BadRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
""",
    )
    violations = mod.find_violations(f)
    assert len(violations) == 1
    assert violations[0].reason == 'extra="allow"'


def test_model_with_ignore_extras_flagged(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "bad_ignore.py",
        """from pydantic import BaseModel, ConfigDict

class BadRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
""",
    )
    violations = mod.find_violations(f)
    assert len(violations) == 1
    assert violations[0].reason == 'extra="ignore"'


def test_non_basemodel_class_ignored(tmp_path: Path) -> None:
    """Plain dataclasses / generic classes must not be flagged."""
    f = _write(
        tmp_path,
        "not_a_model.py",
        """from dataclasses import dataclass

@dataclass
class NotAModel:
    name: str
""",
    )
    assert mod.find_violations(f) == []


def test_subclass_of_request_model_inherits_check(tmp_path: Path) -> None:
    """A subclass of an already-forbid model is still OK (inherits)."""
    f = _write(
        tmp_path,
        "subclass.py",
        """from pydantic import BaseModel, ConfigDict

class Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Child(Base):
    extra_field: str
""",
    )
    # Child inherits Base's config — we only flag direct BaseModel
    # subclasses that lack their own. This matches Pydantic semantics:
    # a child without its own model_config inherits the parent's.
    assert mod.find_violations(f) == []


def test_response_model_exempt(tmp_path: Path) -> None:
    """Response models don't need forbid — they're what the server
    emits, not what it accepts. Exemption is by class name suffix."""
    f = _write(
        tmp_path,
        "response.py",
        """from pydantic import BaseModel

class FooResponse(BaseModel):
    name: str
""",
    )
    assert mod.find_violations(f) == []


def test_multiple_models_some_good_some_bad(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "mixed.py",
        """from pydantic import BaseModel, ConfigDict

class GoodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str

class BadRequest(BaseModel):
    b: int
""",
    )
    violations = mod.find_violations(f)
    assert len(violations) == 1
    assert violations[0].class_name == "BadRequest"


# ---------------------------------------------------------------------------
# scan_paths — whole-tree behaviour
# ---------------------------------------------------------------------------


def test_scan_paths_aggregates_violations(tmp_path: Path) -> None:
    d = tmp_path / "routes"
    d.mkdir()
    _write(
        d,
        "good.py",
        """from pydantic import BaseModel, ConfigDict

class OkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a: str
""",
    )
    _write(
        d,
        "bad.py",
        """from pydantic import BaseModel

class BadRequest(BaseModel):
    b: int
""",
    )
    violations = mod.scan_paths([d])
    assert len(violations) == 1
    assert "bad.py" in str(violations[0].path)


def test_scan_paths_ignores_non_py_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# not python")
    (tmp_path / "config.yaml").write_text("key: value")
    assert mod.scan_paths([tmp_path]) == []


# ---------------------------------------------------------------------------
# Real-repo integration: every route file must be clean
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).parent.parent.parent


def test_real_repo_routes_all_pass_forbid_lint() -> None:
    """This is the guardrail. If this fails, a contributor dropped
    extra='forbid' on a request model in gateway/src/routes/ — restore
    it before merging."""
    routes_dir = REPO_ROOT / "gateway" / "src" / "routes"
    violations = mod.scan_paths([routes_dir])
    assert violations == [], "Pydantic extra='forbid' missing on request models:\n" + "\n".join(
        f"  {v.path.relative_to(REPO_ROOT)}:{v.line} class {v.class_name} — {v.reason}" for v in violations
    )
