"""Regression test for missing jsonschema dep (v0.9.3 regression).

The /v1/execute path calls `_validate_params` which uses jsonschema. If
jsonschema is not installed the route raises ModuleNotFoundError and
returns plain-text 500, bypassing the custom error_response handler.

This test guards against that by:
1. Asserting jsonschema is importable (declared as a runtime dep).
2. Calling _validate_params directly to catch any ImportError regression.
3. Exercising the /v1/execute connector path with invalid-type params to
   prove the route returns 422 (proper RFC 9457 JSON) — not 500.
"""

from __future__ import annotations

import pytest


def test_jsonschema_importable_at_module_level() -> None:
    """jsonschema must be a declared runtime dep of the gateway."""
    from gateway.src.routes import execute

    # Module-level import should have succeeded
    assert hasattr(execute, "jsonschema"), (
        "jsonschema must be imported at module top-level in execute.py "
        "so dep problems surface at startup, not mid-request."
    )


def test_validate_params_does_not_raise_on_valid_input() -> None:
    """_validate_params must not raise for valid input."""
    from gateway.src.routes.execute import _validate_params

    schema = {
        "type": "object",
        "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}},
        "required": ["owner", "repo"],
    }
    err = _validate_params({"owner": "foo", "repo": "bar"}, schema)
    assert err is None


def test_validate_params_returns_message_on_type_mismatch() -> None:
    """Type mismatch must return a string message (not raise)."""
    from gateway.src.routes.execute import _validate_params

    schema = {
        "type": "object",
        "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}},
        "required": ["owner", "repo"],
    }
    err = _validate_params({"owner": 123, "repo": "bar"}, schema)
    assert err is not None
    assert "owner" in err


@pytest.fixture(autouse=True)
def _disable_legacy_execute(monkeypatch):
    """Force production behavior: connector-only gate active."""
    from gateway.src.routes import execute

    monkeypatch.setattr(execute, "_LEGACY_EXECUTE_ENABLED", False)


@pytest.mark.asyncio
async def test_execute_invalid_param_type_returns_422_not_500(client, api_key) -> None:
    """Invalid-type params on a connector tool must return 422 (RFC 9457), not 500.

    This regression was caused by ModuleNotFoundError: No module named 'jsonschema'
    escaping the error handler in v0.9.3.
    """
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "github_get_repo",
            "params": {"owner": 123, "repo": "a2a-playground"},
        },
        headers={"X-API-Key": api_key},
    )
    # Must NOT be plain-text 500 from Starlette's ServerErrorMiddleware
    assert resp.status_code != 500, (
        f"Got 500: body={resp.text!r} — likely a missing dep or unhandled exception escaping error_response()"
    )
    assert resp.status_code == 422
    body = resp.json()
    # RFC 9457 problem details
    assert body["status"] == 422
    assert "invalid-parameter" in body["type"]
    assert "owner" in body["detail"]
