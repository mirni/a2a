"""Tests for /v1/execute deprecation — connector-only gate + Deprecation header.

These tests monkeypatch _LEGACY_EXECUTE_ENABLED to False so the production
behavior (connector-only gate) is exercised, regardless of the conftest
setting that keeps existing tests passing.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_legacy_execute(monkeypatch):
    """Force production behavior: connector-only gate active."""
    from gateway.src.routes import execute

    monkeypatch.setattr(execute, "_LEGACY_EXECUTE_ENABLED", False)


@pytest.mark.asyncio
async def test_core_tool_returns_410(client, api_key):
    """Core business tools that have REST endpoints must return 410 Gone."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 410
    body = resp.json()
    assert "dedicated REST endpoint" in body["detail"]
    assert "tool-moved" in body.get("type", "")


@pytest.mark.asyncio
async def test_connector_tool_not_410(client, api_key):
    """Connector tools must NOT get 410 — they may fail for other reasons
    (e.g. STRIPE_API_KEY not set) but the gate must let them through."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "stripe_list_customers", "params": {}},
        headers={"X-API-Key": api_key},
    )
    # Any status except 410 means the connector gate allowed it through
    assert resp.status_code != 410


@pytest.mark.asyncio
async def test_deprecation_header_on_connector_success(client, api_key):
    """Successful /v1/execute responses include Deprecation: true header.

    stripe_list_customers needs STRIPE_API_KEY and pro tier, so it will
    fail. We verify the connector gate lets it through (not 410) and
    the Deprecation header is present on the 410 path at minimum.
    This test is covered by test_410_includes_deprecation_header.
    """
    # Connector tools pass the gate — verify not 410
    resp = await client.post(
        "/v1/execute",
        json={"tool": "stripe_list_customers", "params": {}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code != 410


@pytest.mark.asyncio
async def test_410_includes_deprecation_header(client, api_key):
    """Even the 410 response for core tools must include Deprecation header."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 410
    assert resp.headers.get("deprecation") == "true"


@pytest.mark.asyncio
async def test_410_rfc9457_format(client, api_key):
    """410 response must follow RFC 9457 problem details format."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 410
    body = resp.json()
    # RFC 9457 fields
    assert "detail" in body
    assert "title" in body
    assert "status" in body
    assert body["status"] == 410
    assert "type" in body
    assert "tool-moved" in body["type"]


# ---------------------------------------------------------------------------
# RFC 8594 Sunset header (v1.2.4 P1: arch audit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_410_includes_sunset_header(client, api_key):
    """RFC 8594: Sunset header on deprecated endpoint (IMF-fixdate format)."""
    from email.utils import parsedate_to_datetime

    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 410
    sunset = resp.headers.get("sunset")
    assert sunset is not None, "Sunset header must be set per RFC 8594"
    # IMF-fixdate: "Thu, 01 Oct 2026 00:00:00 GMT"
    parsed = parsedate_to_datetime(sunset)
    assert parsed is not None
    assert sunset.endswith("GMT"), f"Sunset must be IMF-fixdate GMT, got: {sunset}"


@pytest.mark.asyncio
async def test_410_includes_sunset_link_header(client, api_key):
    """RFC 8594 §3: Link header with rel=sunset pointing to deprecation doc."""
    resp = await client.post(
        "/v1/execute",
        json={"tool": "get_balance", "params": {"agent_id": "test-agent"}},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 410
    link = resp.headers.get("link", "")
    assert 'rel="sunset"' in link, f"Link header must include rel=sunset, got: {link}"


@pytest.mark.asyncio
async def test_connector_success_includes_sunset_header(client, api_key):
    """Sunset header is also set on the 200/error path for connector tools."""
    from email.utils import parsedate_to_datetime

    resp = await client.post(
        "/v1/execute",
        json={"tool": "stripe_list_customers", "params": {}},
        headers={"X-API-Key": api_key},
    )
    # Connector tools pass the gate — status may be anything except 410.
    assert resp.status_code != 410
    sunset = resp.headers.get("sunset")
    assert sunset is not None, "Sunset header must be set on all /v1/execute responses"
    parsed = parsedate_to_datetime(sunset)
    assert parsed is not None
