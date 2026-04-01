"""Tests for disputes REST endpoints — /v1/disputes/."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_held_escrow(client, key, ctx):
    """Create an escrow in 'held' status (required for opening a dispute)."""
    try:
        await ctx.tracker.wallet.create("dispute-payee", initial_balance=0, signup_bonus=False)
    except Exception:
        pass
    resp = await client.post(
        "/v1/payments/escrows",
        json={"payer": "pro-agent", "payee": "dispute-payee", "amount": "100.00"},
        headers={"Authorization": f"Bearer {key}"},
    )
    return resp.json()["id"]


async def _open_dispute(client, key, escrow_id, opener="pro-agent"):
    return await client.post(
        "/v1/disputes",
        json={"escrow_id": escrow_id, "opener": opener, "reason": "Test dispute"},
        headers={"Authorization": f"Bearer {key}"},
    )


# ---------------------------------------------------------------------------
# POST /v1/disputes  (open_dispute)
# ---------------------------------------------------------------------------


async def test_open_dispute_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    escrow_id = await _create_held_escrow(client, pro_api_key, ctx)
    resp = await _open_dispute(client, pro_api_key, escrow_id)
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "Location" in resp.headers


async def test_open_dispute_no_auth(client):
    resp = await client.post(
        "/v1/disputes",
        json={"escrow_id": "fake", "opener": "a", "reason": "x"},
    )
    assert resp.status_code == 401


async def test_open_dispute_extra_fields(client, pro_api_key):
    resp = await client.post(
        "/v1/disputes",
        json={"escrow_id": "fake", "opener": "a", "reason": "x", "extra": 1},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/disputes/{dispute_id}
# ---------------------------------------------------------------------------


async def test_get_dispute_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    escrow_id = await _create_held_escrow(client, pro_api_key, ctx)
    create_resp = await _open_dispute(client, pro_api_key, escrow_id)
    dispute_id = create_resp.json()["id"]
    resp = await client.get(
        f"/v1/disputes/{dispute_id}",
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == dispute_id


# ---------------------------------------------------------------------------
# GET /v1/disputes  (list_disputes)
# ---------------------------------------------------------------------------


async def test_list_disputes_via_rest(client, api_key):
    resp = await client.get(
        "/v1/disputes?agent_id=test-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    assert "disputes" in resp.json()


# ---------------------------------------------------------------------------
# POST /v1/disputes/{dispute_id}/respond
# ---------------------------------------------------------------------------


async def test_respond_to_dispute_via_rest(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    escrow_id = await _create_held_escrow(client, pro_api_key, ctx)
    create_resp = await _open_dispute(client, pro_api_key, escrow_id)
    dispute_id = create_resp.json()["id"]
    # The respondent is the payee of the escrow (dispute-payee).
    # We need a key for that agent. For simplicity, use a pro key
    # and pass the respondent field.
    await ctx.tracker.wallet.create("dispute-payee-2", initial_balance=5000.0, signup_bonus=False)
    payee_key_info = await ctx.key_manager.create_key("dispute-payee", tier="pro")
    payee_key = payee_key_info["key"]
    resp = await client.post(
        f"/v1/disputes/{dispute_id}/respond",
        json={"respondent": "dispute-payee", "response": "We disagree"},
        headers={"Authorization": f"Bearer {payee_key}"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /v1/disputes/{dispute_id}/resolve  (admin only)
# ---------------------------------------------------------------------------


async def test_resolve_dispute_via_rest(client, pro_api_key, admin_api_key):
    ctx = client._transport.app.state.ctx
    escrow_id = await _create_held_escrow(client, pro_api_key, ctx)
    create_resp = await _open_dispute(client, pro_api_key, escrow_id)
    dispute_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/disputes/{dispute_id}/resolve",
        json={
            "resolution": "refund",
            "resolved_by": "admin-agent",
            "notes": "Resolved by admin",
        },
        headers={"Authorization": f"Bearer {admin_api_key}"},
    )
    assert resp.status_code == 200


async def test_resolve_dispute_forbidden_for_non_admin(client, pro_api_key):
    ctx = client._transport.app.state.ctx
    escrow_id = await _create_held_escrow(client, pro_api_key, ctx)
    create_resp = await _open_dispute(client, pro_api_key, escrow_id)
    dispute_id = create_resp.json()["id"]
    resp = await client.post(
        f"/v1/disputes/{dispute_id}/resolve",
        json={"resolution": "refund", "resolved_by": "pro-agent"},
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Response headers
# ---------------------------------------------------------------------------


async def test_disputes_response_headers(client, api_key):
    resp = await client.get(
        "/v1/disputes?agent_id=test-agent",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert "X-Charged" in resp.headers
    assert "X-Request-ID" in resp.headers
