"""v1.2.4 audit P0-2: ``/v1/execute`` must dispatch on route-hit first.

External personas hitting ``/v1/execute`` with garbage, missing-field,
or extra-field bodies must receive a ``410 Gone`` with RFC 8594
``Deprecation``, ``Sunset`` and ``Link`` headers — not a ``422``
``Extra fields are not allowed`` or ``400 Missing 'tool' field``.

The test file intentionally runs without ``A2A_LEGACY_EXECUTE=1`` so
it exercises the production path where legacy execute is dead.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _call_execute(client, body, api_key=None, *, raw=False, monkeypatch=None):
    """Call /v1/execute with ``A2A_LEGACY_EXECUTE`` temporarily unset."""
    import os

    from gateway.src.routes import execute as execute_module

    prev = os.environ.pop("A2A_LEGACY_EXECUTE", None)
    prev_flag = execute_module._LEGACY_EXECUTE_ENABLED
    execute_module._LEGACY_EXECUTE_ENABLED = False
    try:
        headers = {}
        if api_key is not None:
            headers["Authorization"] = f"Bearer {api_key}"
        if raw:
            resp = await client.post("/v1/execute", content=body, headers=headers)
        else:
            resp = await client.post("/v1/execute", json=body, headers=headers)
        return resp
    finally:
        execute_module._LEGACY_EXECUTE_ENABLED = prev_flag
        if prev is not None:
            os.environ["A2A_LEGACY_EXECUTE"] = prev


class TestExecuteDeprecation:
    """/v1/execute must always return 410 Gone in production mode,
    regardless of body content.
    """

    async def test_valid_legacy_body_returns_410(self, client, api_key):
        """Valid body targeting a non-connector tool → 410 Gone."""
        resp = await _call_execute(
            client,
            {"tool": "get_balance", "params": {"agent_id": "test-agent"}},
            api_key=api_key,
        )
        assert resp.status_code == 410
        # RFC 8594 headers
        assert resp.headers.get("deprecation") == "true"
        assert "Sunset" in resp.headers or "sunset" in resp.headers
        assert "Link" in resp.headers or "link" in resp.headers

    async def test_missing_tool_field_returns_410(self, client, api_key):
        """``{"params": {}}`` (no tool) must still return 410, not 400."""
        resp = await _call_execute(client, {"params": {}}, api_key=api_key)
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"

    async def test_extra_fields_returns_410(self, client, api_key):
        """Extra fields must return 410, not 422 ``extra_forbidden``."""
        resp = await _call_execute(
            client,
            {"tool": "get_balance", "params": {}, "unexpected": "field"},
            api_key=api_key,
        )
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"

    async def test_garbage_body_returns_410(self, client, api_key):
        """Non-JSON body must return 410, not 400 ``bad_request``."""
        resp = await _call_execute(
            client,
            b"this is not json at all",
            api_key=api_key,
            raw=True,
        )
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"

    async def test_empty_body_returns_410(self, client, api_key):
        """Empty body must return 410."""
        resp = await _call_execute(client, b"", api_key=api_key, raw=True)
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"

    async def test_array_body_returns_410(self, client, api_key):
        """Non-object body (array) must return 410."""
        resp = await _call_execute(client, [1, 2, 3], api_key=api_key)
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"

    async def test_unknown_tool_returns_410(self, client, api_key):
        """Unknown tool name → 410, not 400 ``unknown_tool``."""
        resp = await _call_execute(
            client,
            {"tool": "nonexistent_tool_xyz", "params": {}},
            api_key=api_key,
        )
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"

    async def test_410_body_is_rfc9457_problem(self, client, api_key):
        """Response body is RFC 9457 problem+json."""
        resp = await _call_execute(
            client,
            {"tool": "get_balance", "params": {}},
            api_key=api_key,
        )
        assert resp.status_code == 410
        body = resp.json()
        assert body.get("status") == 410
        assert "title" in body or "detail" in body or "message" in body

    async def test_410_includes_sunset_and_link_headers(self, client, api_key):
        """RFC 8594 compliance: Sunset date and Link rel=sunset."""
        resp = await _call_execute(
            client,
            {"tool": "get_balance", "params": {}},
            api_key=api_key,
        )
        assert resp.status_code == 410
        sunset = resp.headers.get("sunset") or resp.headers.get("Sunset")
        assert sunset is not None and "GMT" in sunset
        link = resp.headers.get("link") or resp.headers.get("Link")
        assert link is not None
        assert "rel=" in link.lower()

    async def test_410_returned_even_without_auth(self, client):
        """Unauthenticated callers must also see 410, not 401.

        The route is dead — auth is irrelevant. This prevents leaking
        auth-error signals on a decommissioned endpoint.
        """
        resp = await _call_execute(
            client,
            {"tool": "get_balance", "params": {}},
        )
        assert resp.status_code == 410
        assert resp.headers.get("deprecation") == "true"
