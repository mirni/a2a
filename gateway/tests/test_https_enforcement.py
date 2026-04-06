"""Tests for audit H2: HTTP→HTTPS enforcement middleware.

Cloudflare sets X-Forwarded-Proto when terminating TLS. When FORCE_HTTPS
is enabled, plaintext HTTP requests (X-Forwarded-Proto: http) must be
redirected to HTTPS. This is defense-in-depth alongside Cloudflare's
"Always Use HTTPS" rule.

Safe methods (GET/HEAD/OPTIONS) → 308 Permanent Redirect with Location
header pointing at https:// equivalent.

Mutating methods (POST/PUT/PATCH/DELETE) → 400 with RFC 9457 typed
error, refusing to handle the request over plaintext (clients must
not retry a POST on a redirect without user consent per RFC 7231).

The middleware reads FORCE_HTTPS from the environment at request time
so ops can toggle the flag without a process restart.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestHttpsEnforcementDisabled:
    """When FORCE_HTTPS is off, plaintext requests pass through."""

    async def test_http_health_works_when_disabled(self, client, monkeypatch):
        monkeypatch.setenv("FORCE_HTTPS", "0")
        resp = await client.get("/v1/health", headers={"X-Forwarded-Proto": "http"})
        assert resp.status_code == 200

    async def test_http_health_works_when_unset(self, client, monkeypatch):
        """FORCE_HTTPS unset → no enforcement (backwards compatible)."""
        monkeypatch.delenv("FORCE_HTTPS", raising=False)
        resp = await client.get("/v1/health", headers={"X-Forwarded-Proto": "http"})
        assert resp.status_code == 200


class TestHttpsEnforcementEnabled:
    """When FORCE_HTTPS is on, plaintext → redirect or reject."""

    async def test_plain_http_get_redirected_308(self, client, monkeypatch):
        """GET over HTTP → 308 Permanent Redirect to HTTPS."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.get(
            "/v1/health",
            headers={"X-Forwarded-Proto": "http", "Host": "api.greenhelix.net"},
        )
        assert resp.status_code == 308
        location = resp.headers.get("location", "")
        assert location.startswith("https://api.greenhelix.net")
        assert location.endswith("/v1/health")

    async def test_plain_http_head_redirected_308(self, client, monkeypatch):
        """HEAD is a safe method — also redirected."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.head(
            "/v1/health",
            headers={"X-Forwarded-Proto": "http", "Host": "api.greenhelix.net"},
        )
        assert resp.status_code == 308

    async def test_plain_http_options_redirected_308(self, client, monkeypatch):
        """OPTIONS is a safe method — also redirected."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.options(
            "/v1/health",
            headers={"X-Forwarded-Proto": "http", "Host": "api.greenhelix.net"},
        )
        assert resp.status_code == 308

    async def test_plain_http_post_rejected_400(self, client, monkeypatch):
        """POST over HTTP refused with RFC 9457 400 (don't silently redirect mutations)."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.post(
            "/v1/register",
            headers={"X-Forwarded-Proto": "http"},
            json={},
        )
        assert resp.status_code == 400
        assert resp.headers.get("content-type", "").startswith("application/problem+json")
        body = resp.json()
        assert body["type"] == "https://api.greenhelix.net/errors/https-required"
        assert body["status"] == 400

    async def test_plain_http_put_rejected_400(self, client, monkeypatch):
        """PUT over HTTP refused with 400."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.put(
            "/v1/marketplace/services/foo",
            headers={"X-Forwarded-Proto": "http"},
            json={},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "https://api.greenhelix.net/errors/https-required"

    async def test_plain_http_delete_rejected_400(self, client, monkeypatch):
        """DELETE over HTTP refused with 400."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.delete(
            "/v1/marketplace/services/foo",
            headers={"X-Forwarded-Proto": "http"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["type"] == "https://api.greenhelix.net/errors/https-required"

    async def test_https_forwarded_proto_passes(self, client, monkeypatch):
        """X-Forwarded-Proto: https → request handled normally."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.get("/v1/health", headers={"X-Forwarded-Proto": "https"})
        assert resp.status_code == 200

    async def test_no_forwarded_proto_header_passes(self, client, monkeypatch):
        """No X-Forwarded-Proto → assume trusted upstream (direct Uvicorn connection)."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.get("/v1/health")
        assert resp.status_code == 200

    async def test_redirect_preserves_query_string(self, client, monkeypatch):
        """Query string must be preserved in the Location header."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.get(
            "/v1/pricing?limit=5&offset=10",
            headers={"X-Forwarded-Proto": "http", "Host": "api.greenhelix.net"},
        )
        assert resp.status_code == 308
        location = resp.headers.get("location", "")
        assert "limit=5" in location
        assert "offset=10" in location

    async def test_case_insensitive_header_value(self, client, monkeypatch):
        """X-Forwarded-Proto: HTTP (uppercase) → should still redirect."""
        monkeypatch.setenv("FORCE_HTTPS", "1")
        resp = await client.get(
            "/v1/health",
            headers={"X-Forwarded-Proto": "HTTP", "Host": "api.greenhelix.net"},
        )
        assert resp.status_code == 308
