"""v1.2.4 audit P1 T-2: route enumeration contract.

Every live route under ``/v1/*`` must be *observably* covered by
at least one test file. This doesn't guarantee semantic coverage
— only that someone, somewhere, has a test that mentions the
route path. It catches the class of regression where a new
endpoint lands without any test at all, which is how two P0
findings slipped through four consecutive releases.

Design
======

1. Walk ``app.routes`` at fixture time.
2. For each declared route that starts with ``/v1`` and is not
   ``include_in_schema=False``, compute a **path prefix key**:
   the route path with every ``{param}`` stripped and the leading
   segments kept so ``/v1/billing/wallets/{agent_id}/balance`` →
   ``/v1/billing/wallets``.
3. Grep every file under ``gateway/tests/`` for a literal string
   that contains that prefix.
4. Assert the set of uncovered routes is a subset of the
   explicit allow-list (documenting known gaps).

The tests are deliberately tolerant: they only assert that the
*prefix* is mentioned somewhere, not that each HTTP method is
individually probed. That's cheap enough to run on every PR
while still catching the "new route without any test" case.

Admin-only routes
=================

Additionally, for every route that lives under ``/v1/infra/*``,
we assert that *at least one* test file also mentions the string
``403`` within ~60 lines of the route path — a best-effort
heuristic for "there is a non-admin-denied test case". Anything
stronger would require full AST parsing.

Allow-list
==========

``_ALLOWLISTED_UNTESTED`` contains routes that are knowingly
uncovered today. Adding a route to the allow-list requires a
comment explaining why. Empty-target default is enforced.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from fastapi.routing import APIRoute

pytestmark = pytest.mark.asyncio


# Routes that are known to be uncovered. Keep this empty if at
# all possible — the whole point of the gate is to be tripped by
# new untested routes.
_ALLOWLISTED_UNTESTED: set[str] = set()


_TESTS_ROOT = pathlib.Path(__file__).resolve().parent


def _route_prefix(path: str) -> str:
    """Strip ``{param}`` segments and trailing slashes.

    ``/v1/billing/wallets/{agent_id}/balance`` →
    ``/v1/billing/wallets/`` (keeps the fixed-prefix only).
    We keep up to the first ``{param}`` because that's usually
    the most searchable stable substring.
    """
    # Take up to the first `{` — that's the longest stable prefix.
    idx = path.find("{")
    if idx != -1:
        path = path[:idx]
    return path.rstrip("/")


def _all_test_files() -> list[pathlib.Path]:
    return sorted(p for p in _TESTS_ROOT.rglob("test_*.py") if "__pycache__" not in p.parts)


def _load_combined_test_text() -> str:
    chunks: list[str] = []
    for path in _all_test_files():
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def _enumerate_v1_routes(app) -> list[tuple[str, APIRoute]]:
    out: list[tuple[str, APIRoute]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/v1"):
            continue
        if not getattr(route, "include_in_schema", True):
            continue
        out.append((route.path, route))
    return out


class TestRouteEnumerationContract:
    async def test_every_v1_route_has_some_test_file_reference(self, app):
        """Every ``/v1/*`` route prefix must appear in some test file."""
        routes = _enumerate_v1_routes(app)
        assert routes, "no /v1 routes discovered — test harness broken"

        combined = _load_combined_test_text()

        uncovered: list[str] = []
        for path, _route in routes:
            prefix = _route_prefix(path)
            # Require at least one literal occurrence in tests.
            if prefix not in combined:
                uncovered.append(path)

        # Allow-list subset check.
        unexpected = sorted(set(uncovered) - _ALLOWLISTED_UNTESTED)
        assert not unexpected, (
            f"The following /v1/* routes have no test file that "
            f"mentions their prefix. Either add a targeted test or, "
            f"if the route is intentionally untested, add it to "
            f"_ALLOWLISTED_UNTESTED with a comment explaining why. "
            f"Untested: {unexpected}"
        )

    async def test_admin_only_routes_have_403_probe(self, app):
        """Every ``/v1/infra/*`` route needs a test mentioning 403.

        This is a heuristic: we look for the route prefix within
        ~60 lines of a ``403`` token in any test file. It catches
        the class of bug where an admin-only route lands without
        a non-admin denial test.
        """
        routes = _enumerate_v1_routes(app)
        infra_routes = [p for p, _r in routes if p.startswith("/v1/infra")]
        assert infra_routes, "no /v1/infra routes found — test harness broken"

        # Build a combined text with line numbers per file so we
        # can check proximity between route path and '403'.
        missing: list[str] = []
        test_files = _all_test_files()

        for path in infra_routes:
            prefix = _route_prefix(path)
            has_pair = False
            for tf in test_files:
                try:
                    text = tf.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if prefix not in text:
                    continue
                # Check any `403` appears within 60 lines of the prefix.
                for m in re.finditer(re.escape(prefix), text):
                    start = max(0, text.rfind("\n", 0, m.start()) - 60 * 120)
                    end = min(len(text), m.end() + 60 * 120)
                    window = text[start:end]
                    if "403" in window:
                        has_pair = True
                        break
                if has_pair:
                    break
            if not has_pair:
                missing.append(path)

        assert not missing, (
            f"Admin-only routes without a 403-proximity test: {missing}. "
            f"Add a non-admin-denial case for each (see "
            f"gateway/tests/v1/test_infra_admin_gate.py for the pattern)."
        )
