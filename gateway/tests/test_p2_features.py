"""Tests for P2 features: SLA enforcement, strategy marketplace, analytics,
multi-party splits, messaging gateway, historical claims gateway, Swagger UI (TDD)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Historical claim chain (gateway wiring)
# ---------------------------------------------------------------------------


async def test_build_claim_chain_via_gateway(client, pro_api_key, app):
    """Build a Merkle tree of attestations via gateway."""
    ctx = app.state.ctx
    await ctx.identity_api.register_agent("chain-bot")
    await ctx.identity_api.submit_metrics("chain-bot", {"sharpe_30d": 2.5})
    await ctx.identity_api.submit_metrics("chain-bot", {"sharpe_30d": 3.0})

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "build_claim_chain",
            "params": {"agent_id": "chain-bot"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["leaf_count"] == 2
    assert len(result["merkle_root"]) == 64  # SHA3-256 hex


async def test_get_claim_chains_via_gateway(client, pro_api_key, app):
    """Get stored claim chains for an agent."""
    ctx = app.state.ctx
    await ctx.identity_api.register_agent("chain-bot-2")
    await ctx.identity_api.submit_metrics("chain-bot-2", {"sharpe_30d": 1.5})
    await ctx.identity_api.build_claim_chain("chain-bot-2")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_claim_chains",
            "params": {"agent_id": "chain-bot-2"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result["chains"]) == 1


# ---------------------------------------------------------------------------
# Messaging (gateway wiring)
# ---------------------------------------------------------------------------


async def test_send_message_via_gateway(client, pro_api_key):
    """Send a message between agents."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "send_message",
            "params": {
                "sender": "pro-agent",
                "recipient": "other-agent",
                "message_type": "text",
                "subject": "Hello",
                "body": "Interested in your signal feed",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["sender"] == "pro-agent"
    assert result["recipient"] == "other-agent"
    assert "id" in result


async def test_get_messages_via_gateway(client, pro_api_key, app):
    """Get messages for an agent."""
    ctx = app.state.ctx
    await ctx.messaging_api.send_message(sender="sender-x", recipient="pro-agent", message_type="text", body="Hello")

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_messages",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result["messages"]) >= 1


async def test_negotiate_price_via_gateway(client, pro_api_key):
    """Start a price negotiation between agents."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "negotiate_price",
            "params": {
                "initiator": "pro-agent",
                "responder": "signal-provider",
                "amount": 50.0,
                "service_id": "signal-feed-1",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "proposed"
    assert result["proposed_amount"] == 50.0


# ---------------------------------------------------------------------------
# SLA enforcement
# ---------------------------------------------------------------------------


async def test_check_sla_compliance_via_gateway(client, pro_api_key, app):
    """Check SLA compliance for a service."""
    ctx = app.state.ctx
    # Register a trust server
    from trust_src.models import TransportType

    server = await ctx.trust_api.register_server(
        name="test-svc", url="http://example.com", transport_type=TransportType.HTTP
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "check_sla_compliance",
            "params": {
                "server_id": server.id,
                "claimed_uptime": 99.5,
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "compliant" in result
    assert "actual_uptime" in result


# ---------------------------------------------------------------------------
# Strategy marketplace
# ---------------------------------------------------------------------------


async def test_list_strategies_via_gateway(client, pro_api_key, app):
    """List strategy marketplace entries."""
    ctx = app.state.ctx
    from marketplace_src.models import PricingModel, PricingModelType, ServiceCreate

    await ctx.marketplace.register_service(
        ServiceCreate(
            provider_id="strategy-bot",
            name="Alpha Signal Feed",
            description="Daily trading signals",
            category="strategy",
            tools=["get_signal"],
            tags=["trading", "signals", "strategy"],
            pricing=PricingModel(model=PricingModelType.PER_CALL, cost=1.0),
        )
    )

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "list_strategies",
            "params": {"min_trust_score": 0.0},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result["strategies"]) >= 1
    assert result["strategies"][0]["category"] == "strategy"


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


async def test_get_service_analytics_via_gateway(client, api_key, app):
    """Get analytics for an agent's service usage."""
    ctx = app.state.ctx
    # Record some usage
    await ctx.tracker.storage.record_usage(agent_id="test-agent", function="get_balance", cost=0.0)
    await ctx.tracker.storage.record_usage(agent_id="test-agent", function="create_intent", cost=0.2)
    await ctx.tracker.storage.record_usage(agent_id="test-agent", function="create_intent", cost=0.3)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_service_analytics",
            "params": {"agent_id": "test-agent"},
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["total_calls"] >= 3
    assert result["total_cost"] >= 0.5


async def test_get_revenue_report_via_gateway(client, pro_api_key, app):
    """Get revenue report for a provider agent."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("customer-x", initial_balance=1000.0)
    # Create a payment to pro-agent
    await ctx.payment_engine.create_intent(payer="customer-x", payee="pro-agent", amount=100.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "get_revenue_report",
            "params": {"agent_id": "pro-agent"},
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert "total_revenue" in result
    assert "payment_count" in result


# ---------------------------------------------------------------------------
# Multi-party payment splits
# ---------------------------------------------------------------------------


async def test_create_split_intent(client, pro_api_key, app):
    """Create a split payment across multiple payees."""
    ctx = app.state.ctx
    await ctx.tracker.wallet.create("payee-a", initial_balance=0.0)
    await ctx.tracker.wallet.create("payee-b", initial_balance=0.0)
    await ctx.tracker.wallet.create("platform-fee", initial_balance=0.0)

    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_split_intent",
            "params": {
                "payer": "pro-agent",
                "amount": 100.0,
                "splits": [
                    {"payee": "payee-a", "percentage": 70},
                    {"payee": "payee-b", "percentage": 20},
                    {"payee": "platform-fee", "percentage": 10},
                ],
                "description": "Signal purchase with platform fee",
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"] == "settled"
    assert len(result["settlements"]) == 3

    # Check balances
    assert await ctx.tracker.wallet.get_balance("payee-a") == 70.0
    assert await ctx.tracker.wallet.get_balance("payee-b") == 20.0
    assert await ctx.tracker.wallet.get_balance("platform-fee") == 10.0


async def test_create_split_intent_invalid_percentages(client, pro_api_key):
    """Split percentages must sum to 100."""
    resp = await client.post(
        "/v1/execute",
        json={
            "tool": "create_split_intent",
            "params": {
                "payer": "pro-agent",
                "amount": 100.0,
                "splits": [
                    {"payee": "a", "percentage": 50},
                    {"payee": "b", "percentage": 30},
                ],
            },
        },
        headers={"Authorization": f"Bearer {pro_api_key}"},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Swagger UI
# ---------------------------------------------------------------------------


async def test_swagger_ui_served(client, api_key):
    """GET /docs should serve HTML with Swagger UI."""
    resp = await client.get("/docs")
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()
