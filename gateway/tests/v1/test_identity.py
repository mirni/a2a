"""Tests for identity REST endpoints — /v1/identity/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _register_agent(client, key, agent_id="id-agent-1"):
    return await client.post(
        "/v1/identity/agents",
        json={"agent_id": agent_id},
        headers={"Authorization": f"Bearer {key}"},
    )


# ---------------------------------------------------------------------------
# POST /v1/identity/agents (register)
# ---------------------------------------------------------------------------


async def test_register_agent_via_rest(client, api_key):
    resp = await _register_agent(client, api_key, "rest-agent-1")
    assert resp.status_code == 201
    body = resp.json()
    assert body["agent_id"] == "rest-agent-1"


async def test_register_agent_no_auth(client):
    resp = await client.post(
        "/v1/identity/agents",
        json={"agent_id": "no-auth"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /v1/identity/agents/{agent_id} (get identity)
# ---------------------------------------------------------------------------


async def test_get_agent_identity_via_rest(client, api_key):
    await _register_agent(client, api_key, "id-get-1")
    resp = await client.get(
        "/v1/identity/agents/id-get-1",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"] == "id-get-1"


async def test_get_agent_identity_not_found(client, api_key):
    resp = await client.get(
        "/v1/identity/agents/nonexistent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["found"] is False


# ---------------------------------------------------------------------------
# POST /v1/identity/agents/{agent_id}/verify
# ---------------------------------------------------------------------------


async def test_verify_agent_via_rest(client, api_key):
    await _register_agent(client, api_key, "verify-1")
    # Sign with key (will use identity API's built-in signing)
    resp = await client.post(
        "/v1/identity/agents/verify-1/verify",
        json={"message": "hello", "signature": "00" * 64},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    # May fail verification (wrong signature) but endpoint should respond
    assert resp.status_code == 200
    assert "valid" in resp.json()


# ---------------------------------------------------------------------------
# GET /v1/identity/agents/{agent_id}/reputation
# ---------------------------------------------------------------------------


async def test_get_agent_reputation_via_rest(client, api_key):
    resp = await client.get(
        "/v1/identity/agents/test-agent/reputation",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/identity/agents/{agent_id}/claims
# ---------------------------------------------------------------------------


async def test_get_verified_claims_via_rest(client, api_key):
    resp = await client.get(
        "/v1/identity/agents/test-agent/claims",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "claims" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/identity/agents/{agent_id}/metrics (submit)
# ---------------------------------------------------------------------------


async def test_submit_metrics_via_rest(client, pro_api_key):
    await _register_agent(client, pro_api_key, "metric-agent")
    resp = await client.post(
        "/v1/identity/agents/metric-agent/metrics",
        json={"metrics": {"p99_latency_ms": 150, "win_rate_30d": 0.75}},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "commitment_hashes" in body


# ---------------------------------------------------------------------------
# GET /v1/identity/agents (search by metrics)
# ---------------------------------------------------------------------------


async def test_search_agents_by_metrics_via_rest(client, pro_api_key):
    resp = await client.get(
        "/v1/identity/agents?metric_name=p99_latency_ms",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "agents" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/identity/agents/{agent_id}/claim-chains (build)
# ---------------------------------------------------------------------------


async def test_build_claim_chain_via_rest(client, pro_api_key):
    await _register_agent(client, pro_api_key, "chain-agent")
    resp = await client.post(
        "/v1/identity/agents/chain-agent/claim-chains",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /v1/identity/agents/{agent_id}/claim-chains
# ---------------------------------------------------------------------------


async def test_get_claim_chains_via_rest(client, pro_api_key):
    resp = await client.get(
        "/v1/identity/agents/pro-agent/claim-chains",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert "chains" in resp.json()


# ---------------------------------------------------------------------------
# Orgs
# ---------------------------------------------------------------------------


async def test_create_org_via_rest(client, api_key):
    resp = await client.post(
        "/v1/identity/orgs",
        json={"org_name": "TestOrg"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "org_id" in body


async def test_get_org_via_rest(client, api_key):
    create_resp = await client.post(
        "/v1/identity/orgs",
        json={"org_name": "GetOrg"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    org_id = create_resp.json()["org_id"]
    resp = await client.get(
        f"/v1/identity/orgs/{org_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["org_id"] == org_id


async def test_add_agent_to_org_via_rest(client, api_key):
    create_resp = await client.post(
        "/v1/identity/orgs",
        json={"org_name": "AddOrg"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    org_id = create_resp.json()["org_id"]
    await _register_agent(client, api_key, "org-member-1")
    resp = await client.post(
        f"/v1/identity/orgs/{org_id}/members",
        json={"agent_id": "org-member-1"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == "org-member-1"


async def test_remove_agent_from_org_via_rest(client, api_key):
    create_resp = await client.post(
        "/v1/identity/orgs",
        json={"org_name": "RemOrg", "agent_id": "test-agent"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    org_id = create_resp.json()["org_id"]
    # Add a second owner so we can remove one
    await _register_agent(client, api_key, "org-rem-agent")
    await client.post(
        f"/v1/identity/orgs/{org_id}/members",
        json={"agent_id": "org-rem-agent", "role": "owner"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    resp = await client.delete(
        f"/v1/identity/orgs/{org_id}/members/org-rem-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["removed"] is True


# ---------------------------------------------------------------------------
# Metrics ingestion/query
# ---------------------------------------------------------------------------


async def test_ingest_metrics_via_rest(client, api_key):
    await _register_agent(client, api_key, "ingest-agent")
    resp = await client.post(
        "/v1/identity/metrics/ingest",
        json={"agent_id": "ingest-agent", "metrics": {"cpu": 0.5}},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200


async def test_query_metrics_via_rest(client, api_key):
    resp = await client.get(
        "/v1/identity/metrics?agent_id=test-agent&metric_name=cpu",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "data" in resp.json()


async def test_get_metric_deltas_via_rest(client, api_key):
    resp = await client.get(
        "/v1/identity/metrics/deltas?agent_id=test-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "deltas" in resp.json()


async def test_get_metric_averages_via_rest(client, api_key):
    resp = await client.get(
        "/v1/identity/metrics/averages?agent_id=test-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "averages" in resp.json()
