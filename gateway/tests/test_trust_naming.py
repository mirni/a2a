"""Tests for P3-7: Standardized naming conventions in trust tools.

Trust tools historically use ``server_id`` but the rest of the platform
uses ``agent_id``.  After the fix every trust tool that accepts
``server_id`` must *also* accept ``agent_id`` as an alias.

When both are supplied, ``server_id`` wins (backward-compatible).
When only ``agent_id`` is supplied, it is used as ``server_id``.
"""

from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_trust_server(app, server_id: str = "srv-naming-1") -> None:
    """Register a server and insert probe/scan data so trust tools work."""
    from trust_src.models import ProbeResult, SecurityScan

    trust_api = app.state.ctx.trust_api

    await trust_api.register_server(
        name="NamingTest",
        url="https://naming.example.com",
        server_id=server_id,
    )

    ts = time.time()
    await trust_api.storage.store_probe_result(
        ProbeResult(
            server_id=server_id,
            timestamp=ts,
            latency_ms=42.0,
            status_code=200,
            tools_count=3,
            tools_documented=3,
        )
    )
    await trust_api.storage.store_security_scan(
        SecurityScan(
            server_id=server_id,
            timestamp=ts,
            tls_enabled=True,
            auth_required=True,
            input_validation_score=90.0,
            cve_count=0,
        )
    )


# ---------------------------------------------------------------------------
# Tests: agent_id alias accepted by trust tools
# ---------------------------------------------------------------------------


class TestTrustNamingAgentIdAlias:
    """Each trust tool that takes ``server_id`` should also accept ``agent_id``."""

    @pytest.mark.asyncio
    async def test_get_trust_score_with_agent_id(self, app, client, api_key):
        """get_trust_score should work when called with agent_id instead of server_id."""
        await _seed_trust_server(app, "srv-score-alias")

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_trust_score",
                "params": {"agent_id": "srv-score-alias"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_id"] == "srv-score-alias"

    @pytest.mark.asyncio
    async def test_delete_server_with_agent_id(self, app, client, pro_api_key):
        """delete_server should accept agent_id."""
        await _seed_trust_server(app, "srv-del-alias")

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "delete_server",
                "params": {"agent_id": "srv-del-alias"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True

    @pytest.mark.asyncio
    async def test_update_server_with_agent_id(self, app, client, pro_api_key):
        """update_server should accept agent_id."""
        await _seed_trust_server(app, "srv-upd-alias")

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "update_server",
                "params": {"agent_id": "srv-upd-alias", "name": "Renamed"},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Renamed"

    @pytest.mark.asyncio
    async def test_check_sla_compliance_with_agent_id(self, app, client, pro_api_key):
        """check_sla_compliance should accept agent_id."""
        await _seed_trust_server(app, "srv-sla-alias")

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "check_sla_compliance",
                "params": {"agent_id": "srv-sla-alias", "claimed_uptime": 99.0},
            },
            headers={"Authorization": f"Bearer {pro_api_key}"},
        )
        assert resp.status_code == 200

    # -----------------------------------------------------------------------
    # Backward compatibility: server_id still works
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_trust_score_server_id_still_works(self, app, client, api_key):
        """Original server_id parameter must keep working."""
        await _seed_trust_server(app, "srv-compat")

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_trust_score",
                "params": {"server_id": "srv-compat"},
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_id"] == "srv-compat"

    # -----------------------------------------------------------------------
    # Precedence: server_id wins when both are supplied
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_server_id_takes_precedence(self, app, client, api_key):
        """When both server_id and agent_id are supplied, server_id wins."""
        await _seed_trust_server(app, "srv-precedence")

        resp = await client.post(
            "/v1/execute",
            json={
                "tool": "get_trust_score",
                "params": {
                    "server_id": "srv-precedence",
                    "agent_id": "should-be-ignored",
                },
            },
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["server_id"] == "srv-precedence"
