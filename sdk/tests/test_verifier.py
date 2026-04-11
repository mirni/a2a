"""Tests for the SDK verifier submodule.

Covers the low-level A2AClient methods and the high-level ``prove_policy``
one-liner. Uses the gateway's ASGI transport + a pro-tier agent (verifier
tools are gated to paid tiers).
"""

from __future__ import annotations

import os
import sys

import pytest

_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import httpx

import gateway.src.bootstrap  # noqa: F401
from gateway.src.app import create_app
from gateway.src.lifespan import lifespan
from sdk.src.a2a_client import A2AClient
from sdk.src.a2a_client.verifier import (
    JsonPolicySpec,
    ProofResult,
    prove_policy,
)


@pytest.fixture
async def gateway_app(tmp_path, monkeypatch):
    data_dir = str(tmp_path)
    monkeypatch.setenv("A2A_DATA_DIR", data_dir)
    monkeypatch.setenv("BILLING_DSN", f"sqlite:///{data_dir}/billing.db")
    monkeypatch.setenv("PAYWALL_DSN", f"sqlite:///{data_dir}/paywall.db")
    monkeypatch.setenv("PAYMENTS_DSN", f"sqlite:///{data_dir}/payments.db")
    monkeypatch.setenv("MARKETPLACE_DSN", f"sqlite:///{data_dir}/marketplace.db")
    monkeypatch.setenv("TRUST_DSN", f"sqlite:///{data_dir}/trust.db")
    monkeypatch.setenv("EVENT_BUS_DSN", f"sqlite:///{data_dir}/event_bus.db")
    monkeypatch.setenv("WEBHOOK_DSN", f"sqlite:///{data_dir}/webhooks.db")

    app = create_app()
    ctx_manager = lifespan(app)
    await ctx_manager.__aenter__()
    yield app
    await ctx_manager.__aexit__(None, None, None)


@pytest.fixture
async def sdk_client(gateway_app):
    transport = httpx.ASGITransport(app=gateway_app)
    client = A2AClient.__new__(A2AClient)
    client.base_url = "http://test"
    client.api_key = None
    client.max_retries = 0
    client.retry_base_delay = 0.0
    client.pricing_cache_ttl = 300.0
    client._pricing_cache = None
    client._pricing_cache_time = 0.0
    client._client = httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30.0)
    yield client
    await client.close()


@pytest.fixture
async def pro_agent(gateway_app, sdk_client):
    """Set up a pro-tier agent with enough balance to run verifications."""
    ctx = gateway_app.state.ctx
    await ctx.tracker.wallet.create("sdk-verifier-agent", initial_balance=5000.0, signup_bonus=False)
    key_info = await ctx.key_manager.create_key("sdk-verifier-agent", tier="pro")
    sdk_client.api_key = key_info["key"]
    return key_info["key"]


_SMT2_POSITIVE = "(declare-const x Int)\n(assert (> x 0))"


# ---------------------------------------------------------------------------
# Low-level A2AClient methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_verification_returns_job(sdk_client, pro_agent):
    """POST /v1/gatekeeper/jobs → typed response with job_id + status."""
    resp = await sdk_client.submit_verification(
        agent_id="sdk-verifier-agent",
        properties=[{"name": "positive_x", "expression": _SMT2_POSITIVE}],
    )
    assert resp.job_id.startswith("vj-")
    assert resp.status in {"pending", "completed", "failed", "timeout"}


@pytest.mark.asyncio
async def test_get_verification_status(sdk_client, pro_agent):
    submitted = await sdk_client.submit_verification(
        agent_id="sdk-verifier-agent",
        properties=[{"name": "positive_x", "expression": _SMT2_POSITIVE}],
    )
    status = await sdk_client.get_verification_status(submitted.job_id)
    assert status.job_id == submitted.job_id
    assert status.agent_id == "sdk-verifier-agent"


@pytest.mark.asyncio
async def test_submit_verification_idempotency_key(sdk_client, pro_agent):
    """Same idempotency_key → same job_id (second call returns cached)."""
    body = {
        "agent_id": "sdk-verifier-agent",
        "properties": [{"name": "positive_x", "expression": _SMT2_POSITIVE}],
        "idempotency_key": "sdk-idem-001",
    }
    r1 = await sdk_client.submit_verification(**body)
    r2 = await sdk_client.submit_verification(**body)
    assert r1.job_id == r2.job_id


# ---------------------------------------------------------------------------
# High-level prove_policy() one-liner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prove_policy_satisfiable(sdk_client, pro_agent):
    """prove_policy returns a ProofResult with satisfied=True for SAT."""
    policy: JsonPolicySpec = {
        "name": "x_in_range",
        "variables": [{"name": "x", "type": "int", "value": 5}],
        "assertions": [
            {"op": ">", "args": ["x", 0]},
            {"op": "<", "args": ["x", 10]},
        ],
    }
    result = await prove_policy(sdk_client, "sdk-verifier-agent", policy)
    assert isinstance(result, ProofResult)
    assert result.satisfied is True
    assert result.job_id.startswith("vj-")
    # The result carries the final status from the verifier.
    assert result.status in {"completed", "failed", "timeout"}


@pytest.mark.asyncio
async def test_prove_policy_unsatisfiable(sdk_client, pro_agent):
    """prove_policy returns satisfied=False for UNSAT (contradictory)."""
    policy: JsonPolicySpec = {
        "name": "impossible",
        "variables": [{"name": "x", "type": "int"}],
        "assertions": [
            {"op": ">", "args": ["x", 10]},
            {"op": "<", "args": ["x", 5]},
        ],
    }
    result = await prove_policy(sdk_client, "sdk-verifier-agent", policy)
    assert isinstance(result, ProofResult)
    assert result.satisfied is False
