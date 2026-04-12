"""Structural test pinning the middleware package split (P1-2).

These tests DO NOT exercise middleware behaviour — the existing
``test_observability``, ``test_public_rate_limit``,
``test_client_ip_middleware``, etc. suites already cover that.

Instead, they pin the *shape* of the post-split package so a future
contributor cannot accidentally re-collapse everything back into one
file (or remove a public symbol that external modules import).

This is the compatibility contract between the new
``gateway.src.middleware`` subpackage and everything that imports
from ``gateway.src.middleware`` today (``gateway.src.app``,
``gateway.src.routes.execute``, tests, mutants, …).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

MIDDLEWARE_PKG = "gateway.src.middleware"

# Public symbols that must remain importable from ``gateway.src.middleware``
# for backwards compatibility. Removing one is a breaking change that
# needs to be co-ordinated with every importer — see the grep in the
# test below for a canonical list.
REQUIRED_PUBLIC_NAMES: tuple[str, ...] = (
    # correlation
    "CorrelationIDMiddleware",
    # security headers
    "SecurityHeadersMiddleware",
    # client ip
    "ClientIpResolutionMiddleware",
    # rate limit
    "PublicRateLimitMiddleware",
    # metrics
    "Metrics",
    "MetricsMiddleware",
    "metrics_handler",
    # body size
    "BodySizeLimitMiddleware",
    "DEFAULT_MAX_BODY_BYTES",
    # request timeout
    "RequestTimeoutMiddleware",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    # logging
    "JSONFormatter",
    "setup_structured_logging",
    # https
    "HttpsEnforcementMiddleware",
    # path/id validation
    "AgentIdLengthMiddleware",
    "EncodedPathRejectionMiddleware",
)

# The new submodule layout. Each file keeps a single concern.
EXPECTED_SUBMODULES: tuple[str, ...] = (
    "correlation",
    "security_headers",
    "client_ip",
    "rate_limit",
    "metrics",
    "body_size",
    "timeout",
    "logging",
    "https",
    "validation",
)

MIDDLEWARE_DIR = Path(__file__).resolve().parent.parent / "src" / "middleware"


# ---------------------------------------------------------------------------
# Layout: ``gateway/src/middleware/`` must exist as a package directory
# ---------------------------------------------------------------------------


def test_middleware_is_a_package_directory() -> None:
    """After P1-2 the split, ``middleware`` is a package, not a single file."""
    assert MIDDLEWARE_DIR.is_dir(), (
        f"Expected {MIDDLEWARE_DIR} to be a directory (middleware package). P1-2 split has been reverted."
    )
    assert (MIDDLEWARE_DIR / "__init__.py").is_file(), f"Missing {MIDDLEWARE_DIR / '__init__.py'}"


def test_legacy_middleware_module_file_is_gone() -> None:
    """The old single-file ``middleware.py`` must not coexist with the package."""
    legacy = MIDDLEWARE_DIR.parent / "middleware.py"
    assert not legacy.exists(), (
        f"{legacy} exists next to the middleware/ package. "
        "Python will pick one or the other depending on sys.path order — "
        "delete the file."
    )


@pytest.mark.parametrize("submodule", EXPECTED_SUBMODULES)
def test_expected_submodule_file_exists(submodule: str) -> None:
    path = MIDDLEWARE_DIR / f"{submodule}.py"
    assert path.is_file(), f"Missing middleware submodule: {path}"


@pytest.mark.parametrize("submodule", EXPECTED_SUBMODULES)
def test_expected_submodule_is_under_200_loc(submodule: str) -> None:
    """Each submodule must stay under 200 LOC — the whole point of P1-2."""
    path = MIDDLEWARE_DIR / f"{submodule}.py"
    loc = len(path.read_text(encoding="utf-8").splitlines())
    assert loc <= 200, f"{submodule}.py is {loc} lines — split further."


# ---------------------------------------------------------------------------
# Public surface: everything that was importable before the split must still
# be importable from ``gateway.src.middleware`` by the same name.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", REQUIRED_PUBLIC_NAMES)
def test_public_name_reexported_from_package(name: str) -> None:
    """Guarantee the compatibility shim is in place."""
    # Force a fresh import so a stale cached module from a previous
    # test run can't mask a genuine regression.
    if MIDDLEWARE_PKG in sys.modules:
        del sys.modules[MIDDLEWARE_PKG]
    mod = importlib.import_module(MIDDLEWARE_PKG)
    assert hasattr(mod, name), (
        f"{MIDDLEWARE_PKG} no longer exports {name!r}. Add it to middleware/__init__.py's re-exports."
    )


def test_package_dunder_all_is_sorted_and_complete() -> None:
    """``__all__`` must contain every public name (sanity check)."""
    if MIDDLEWARE_PKG in sys.modules:
        del sys.modules[MIDDLEWARE_PKG]
    mod = importlib.import_module(MIDDLEWARE_PKG)
    all_names = set(getattr(mod, "__all__", ()))
    missing = [n for n in REQUIRED_PUBLIC_NAMES if n not in all_names]
    assert not missing, (
        f"middleware/__init__.py __all__ is missing names: {missing}. Keep __all__ in sync with REQUIRED_PUBLIC_NAMES."
    )
