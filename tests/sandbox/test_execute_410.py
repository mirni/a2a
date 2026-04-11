"""T-3 sandbox parity: /v1/execute returns 410 Gone unconditionally.

Covers P0-2 on the live stack. The legacy endpoint was the
single hottest source of audit findings — make sure the real
sandbox returns 410 regardless of body shape or auth.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestSandboxExecute410:
    async def test_legacy_body_returns_410(self, sandbox_client, free_key):
        resp = await sandbox_client.post(
            "/v1/execute",
            json={"tool": "health", "params": {}},
            headers={"Authorization": f"Bearer {free_key}"},
        )
        assert resp.status_code == 410, f"/v1/execute should be 410 Gone, got {resp.status_code}"

    async def test_garbage_body_still_410(self, sandbox_client, free_key):
        """Dispatch on route-hit first — never 422, always 410."""
        resp = await sandbox_client.post(
            "/v1/execute",
            json={"nonsense": True, "more_nonsense": [1, 2, 3]},
            headers={"Authorization": f"Bearer {free_key}"},
        )
        assert resp.status_code == 410

    async def test_sunset_header_present(self, sandbox_client, free_key):
        resp = await sandbox_client.post(
            "/v1/execute",
            json={},
            headers={"Authorization": f"Bearer {free_key}"},
        )
        assert resp.status_code == 410
        # Sunset header per RFC 8594. Cloudflare/nginx may normalise case.
        header_keys = {k.lower() for k in resp.headers.keys()}
        assert "sunset" in header_keys, f"missing Sunset header, got headers: {list(resp.headers.keys())}"
