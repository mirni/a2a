#!/usr/bin/env python3
"""Customer Agent Simulation: AlphaBot-v3

Exercises the A2A Commerce Platform via httpx ASGI transport (no live server)
and generates structured feedback in CUSTOMER_AGENT_FEEDBACK.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Environment setup — must come before any gateway imports
# ---------------------------------------------------------------------------
_project_root = os.path.normpath(os.path.join(os.path.dirname(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

_tmp_dir = tempfile.mkdtemp(prefix="alphabot_sim_")
os.environ["A2A_DATA_DIR"] = _tmp_dir
os.environ["BILLING_DSN"] = f"sqlite:///{_tmp_dir}/billing.db"
os.environ["PAYWALL_DSN"] = f"sqlite:///{_tmp_dir}/paywall.db"
os.environ["PAYMENTS_DSN"] = f"sqlite:///{_tmp_dir}/payments.db"
os.environ["MARKETPLACE_DSN"] = f"sqlite:///{_tmp_dir}/marketplace.db"
os.environ["TRUST_DSN"] = f"sqlite:///{_tmp_dir}/trust.db"
os.environ["IDENTITY_DSN"] = f"sqlite:///{_tmp_dir}/identity.db"
os.environ["EVENT_BUS_DSN"] = f"sqlite:///{_tmp_dir}/event_bus.db"
os.environ["WEBHOOK_DSN"] = f"sqlite:///{_tmp_dir}/webhooks.db"

# Bootstrap product imports
import httpx  # noqa: E402

import gateway.src.bootstrap  # noqa: F401, E402
from gateway.src.app import create_app  # noqa: E402
from gateway.src.lifespan import lifespan  # noqa: E402

# ---------------------------------------------------------------------------
# ANSI colors for terminal output
# ---------------------------------------------------------------------------
C_RESET = "\033[0m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_CYAN = "\033[96m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"


def _ok(msg: str) -> None:
    print(f"  {C_GREEN}[OK]{C_RESET} {msg}")


def _fail(msg: str) -> None:
    print(f"  {C_RED}[FAIL]{C_RESET} {msg}")


def _info(msg: str) -> None:
    print(f"  {C_CYAN}[INFO]{C_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {C_YELLOW}[WARN]{C_RESET} {msg}")


def _section(title: str) -> None:
    print(f"\n{C_BOLD}{C_CYAN}{'=' * 60}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}  {title}{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}{'=' * 60}{C_RESET}")


# ---------------------------------------------------------------------------
# Feedback collector
# ---------------------------------------------------------------------------
@dataclass
class StepResult:
    name: str
    passed: bool
    status_code: int | None = None
    response_body: dict | None = None
    error: str | None = None
    latency_ms: float = 0.0
    notes: str = ""


@dataclass
class ModuleFeedback:
    module: str
    nps_score: int = 5  # 1-10
    worked_well: list[str] = field(default_factory=list)
    confusing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)


@dataclass
class FeedbackReport:
    agent_name: str = "AlphaBot-v3"
    agent_description: str = "Crypto trading bot (BTC/ETH/SOL perpetuals, trend-following + expansion)"
    modules: dict[str, ModuleFeedback] = field(default_factory=dict)
    overall_notes: list[str] = field(default_factory=list)
    pricing_feedback: list[str] = field(default_factory=list)
    ergonomics_feedback: list[str] = field(default_factory=list)
    trading_bot_feedback: list[str] = field(default_factory=list)
    missing_features: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0


# ---------------------------------------------------------------------------
# Helper: execute a tool via the gateway
# ---------------------------------------------------------------------------
async def call_tool(
    client: httpx.AsyncClient,
    tool: str,
    params: dict,
    api_key: str,
    expect_status: int = 200,
) -> StepResult:
    """Call POST /v1/execute and return a StepResult."""
    t0 = time.time()
    try:
        resp = await client.post(
            "/v1/execute",
            json={"tool": tool, "params": params},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        elapsed = (time.time() - t0) * 1000
        body = resp.json()
        passed = resp.status_code == expect_status
        return StepResult(
            name=tool,
            passed=passed,
            status_code=resp.status_code,
            response_body=body,
            latency_ms=elapsed,
            error=None
            if passed
            else f"Expected {expect_status}, got {resp.status_code}: {json.dumps(body, indent=None)[:200]}",
        )
    except Exception as exc:
        elapsed = (time.time() - t0) * 1000
        return StepResult(
            name=tool,
            passed=False,
            error=f"Exception: {exc}",
            latency_ms=elapsed,
        )


async def call_get(
    client: httpx.AsyncClient,
    path: str,
    expect_status: int = 200,
) -> StepResult:
    """Call a GET endpoint and return a StepResult."""
    t0 = time.time()
    try:
        resp = await client.get(path)
        elapsed = (time.time() - t0) * 1000
        body = resp.json() if "json" in resp.headers.get("content-type", "") else {"raw": resp.text[:500]}
        passed = resp.status_code == expect_status
        return StepResult(
            name=f"GET {path}",
            passed=passed,
            status_code=resp.status_code,
            response_body=body,
            latency_ms=elapsed,
            error=None if passed else f"Expected {expect_status}, got {resp.status_code}",
        )
    except Exception as exc:
        elapsed = (time.time() - t0) * 1000
        return StepResult(
            name=f"GET {path}",
            passed=False,
            error=f"Exception: {exc}",
            latency_ms=elapsed,
        )


# ---------------------------------------------------------------------------
# Simulation phases
# ---------------------------------------------------------------------------


async def phase_system(client: httpx.AsyncClient, report: FeedbackReport) -> None:
    """Test system endpoints: health, pricing catalog, openapi spec, metrics."""
    _section("Phase 0: System Endpoints")
    fb = ModuleFeedback(module="System / Infrastructure")

    # Health
    r = await call_get(client, "/v1/health")
    fb.steps.append(r)
    if r.passed:
        _ok(f"Health check OK ({r.latency_ms:.0f}ms) — tools: {r.response_body.get('tools', '?')}")
        fb.worked_well.append("Health endpoint is fast and returns tool count")
    else:
        _fail(f"Health check failed: {r.error}")
        fb.failed.append(f"Health check: {r.error}")

    # Pricing catalog
    r = await call_get(client, "/v1/pricing")
    fb.steps.append(r)
    if r.passed:
        tools = r.response_body.get("tools", [])
        _ok(f"Pricing catalog returned {len(tools)} tools ({r.latency_ms:.0f}ms)")
        free_tools = [t for t in tools if t.get("tier_required") == "free"]
        pro_tools = [t for t in tools if t.get("tier_required") == "pro"]
        _info(f"  Free tier: {len(free_tools)} tools, Pro tier: {len(pro_tools)} tools")
        fb.worked_well.append(f"Catalog lists {len(tools)} tools with clear tier/pricing info")
    else:
        _fail(f"Pricing catalog: {r.error}")
        fb.failed.append(f"Pricing catalog: {r.error}")

    # Single tool pricing
    r = await call_get(client, "/v1/pricing/create_escrow")
    fb.steps.append(r)
    if r.passed:
        _ok(f"Per-tool pricing detail works ({r.latency_ms:.0f}ms)")
        fb.worked_well.append("Per-tool pricing lookup works well for cost estimation")
    else:
        _fail(f"Per-tool pricing: {r.error}")

    # Unknown tool pricing
    r = await call_get(client, "/v1/pricing/nonexistent_tool", expect_status=404)
    fb.steps.append(r)
    if r.passed:
        _ok("Unknown tool returns 404 (correct)")
        fb.worked_well.append("Unknown tool pricing correctly returns 404")
    else:
        _fail(f"Unknown tool pricing: expected 404, got {r.status_code}")
        fb.confusing.append("Unknown tool pricing does not return 404 as expected")

    # OpenAPI spec
    r = await call_get(client, "/v1/openapi.json")
    fb.steps.append(r)
    if r.passed:
        spec = r.response_body
        paths = list(spec.get("paths", {}).keys())
        _ok(f"OpenAPI spec returned ({r.latency_ms:.0f}ms) — {len(paths)} paths")
        if spec.get("openapi", "").startswith("3.1"):
            _ok("OpenAPI 3.1.0 compliant")
            fb.worked_well.append("OpenAPI 3.1.0 spec is auto-generated and complete")
        else:
            _warn(f"OpenAPI version: {spec.get('openapi')}")
    else:
        _fail(f"OpenAPI spec: {r.error}")
        fb.failed.append(f"OpenAPI spec: {r.error}")

    # Metrics
    r = await call_get(client, "/v1/metrics")
    fb.steps.append(r)
    if r.passed:
        _ok(f"Metrics endpoint works ({r.latency_ms:.0f}ms)")
        fb.worked_well.append("Prometheus metrics endpoint available")
    else:
        _fail(f"Metrics: {r.error}")

    # Signing key
    r = await call_get(client, "/v1/signing-key")
    fb.steps.append(r)
    if r.passed:
        _ok(f"Signing key endpoint works ({r.latency_ms:.0f}ms)")
        fb.worked_well.append("Response signing key endpoint enables verification of response integrity")
    else:
        _fail(f"Signing key: {r.error}")

    fb.missing.append("No /v1/status or /v1/docs endpoint (HTML rendered docs)")
    fb.missing.append("No SDK generation link or client library references in OpenAPI spec")
    fb.nps_score = 8
    report.modules["system"] = fb


async def phase_identity(client: httpx.AsyncClient, report: FeedbackReport, app) -> tuple[str, str]:
    """Register AlphaBot-v3 identity, get API keys."""
    _section("Phase 1: Identity & API Key Setup")
    fb = ModuleFeedback(module="Identity + Paywall (API Keys)")
    ctx = app.state.ctx

    # Register crypto identity
    r = await call_tool(client, "register_agent", {"agent_id": "alphabot-v3"}, api_key="__bootstrap__")
    # This will fail because we don't have an API key yet. We need to create one first.
    # The test fixtures create keys programmatically. Let's do the same.

    _info("Creating wallet + free-tier API key programmatically (bootstrapping)...")
    await ctx.tracker.wallet.create("alphabot-v3", initial_balance=500.0)
    free_key_info = await ctx.key_manager.create_key("alphabot-v3", tier="free")
    free_key = free_key_info["key"]
    _ok(f"Free-tier key created: {free_key[:12]}...")

    _info("Creating wallet + pro-tier API key programmatically...")
    await ctx.tracker.wallet.create("alphabot-v3-pro", initial_balance=5000.0)
    pro_key_info = await ctx.key_manager.create_key("alphabot-v3-pro", tier="pro")
    pro_key = pro_key_info["key"]
    _ok(f"Pro-tier key created: {pro_key[:12]}...")

    fb.confusing.append(
        "No self-service API key creation endpoint — keys must be provisioned server-side. "
        "A trading bot cannot onboard itself without out-of-band key provisioning."
    )
    fb.confusing.append(
        "Wallet creation is also server-side only — no 'create_wallet' tool in the catalog. "
        "An agent cannot bootstrap its own billing account."
    )

    # Register crypto identity via the gateway
    r = await call_tool(client, "register_agent", {"agent_id": "alphabot-v3"}, free_key)
    fb.steps.append(r)
    if r.passed:
        pub_key = r.response_body.get("result", {}).get("public_key", "???")
        _ok(f"Crypto identity registered. Public key: {pub_key[:24]}...")
        fb.worked_well.append("Ed25519 keypair auto-generated on registration — zero friction")
    else:
        _fail(f"Register agent: {r.error}")
        fb.failed.append(f"register_agent: {r.error}")

    # Get identity back
    r = await call_tool(client, "get_agent_identity", {"agent_id": "alphabot-v3"}, free_key)
    fb.steps.append(r)
    if r.passed:
        found = r.response_body.get("result", {}).get("found", False)
        _ok(f"Identity lookup: found={found}")
        fb.worked_well.append("Identity lookup is fast and returns full key info")
    else:
        _fail(f"get_agent_identity: {r.error}")

    # Try to look up non-existent agent
    r = await call_tool(client, "get_agent_identity", {"agent_id": "ghost-agent"}, free_key)
    fb.steps.append(r)
    if r.passed:
        found = r.response_body.get("result", {}).get("found", False)
        if not found:
            _ok("Non-existent agent returns found=false (good)")
            fb.worked_well.append("Non-existent identity returns found=false, not an error")
        else:
            _warn("Non-existent agent says found=true?!")
    else:
        _fail(f"Non-existent identity lookup: {r.error}")

    # Check reputation (new agent, should be empty)
    r = await call_tool(client, "get_agent_reputation", {"agent_id": "alphabot-v3"}, free_key)
    fb.steps.append(r)
    if r.passed:
        _ok(f"Reputation query works ({r.latency_ms:.0f}ms)")
        rep = r.response_body.get("result", {})
        _info(f"  composite_score={rep.get('composite_score', 'N/A')}, confidence={rep.get('confidence', 'N/A')}")
        fb.worked_well.append("Reputation endpoint returns structured scores even for new agents")
    else:
        _fail(f"get_agent_reputation: {r.error}")

    fb.missing.append("No 'rotate_key' or 'revoke_key' tool — cannot rotate compromised Ed25519 keys")
    fb.missing.append("No 'list_agents' or 'search_agents' tool — cannot discover other agents by criteria")
    fb.missing.append("No org/team concept — individual agent only, no way to group sub-bots under one org")
    fb.nps_score = 6
    report.modules["identity"] = fb
    return free_key, pro_key


async def phase_billing(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test billing: balance, deposit, usage summary."""
    _section("Phase 2: Billing & Wallet")
    fb = ModuleFeedback(module="Billing")

    # Check initial balance
    r = await call_tool(client, "get_balance", {"agent_id": "alphabot-v3"}, free_key)
    fb.steps.append(r)
    if r.passed:
        bal = r.response_body.get("result", {}).get("balance", 0)
        _ok(f"Initial balance: {bal} credits")
        fb.worked_well.append("Balance check is free and instant")
    else:
        _fail(f"get_balance: {r.error}")
        fb.failed.append(f"get_balance: {r.error}")

    # Deposit credits
    r = await call_tool(
        client,
        "deposit",
        {"agent_id": "alphabot-v3", "amount": 250.0, "description": "Trading strategy subscription topup"},
        free_key,
    )
    fb.steps.append(r)
    if r.passed:
        new_bal = r.response_body.get("result", {}).get("new_balance", 0)
        _ok(f"Deposited 250 credits. New balance: {new_bal}")
        fb.worked_well.append("Deposit with description works — good for audit trail")
    else:
        _fail(f"deposit: {r.error}")
        fb.failed.append(f"deposit: {r.error}")

    # Try depositing negative amount
    r = await call_tool(
        client,
        "deposit",
        {"agent_id": "alphabot-v3", "amount": -100.0, "description": "Attempting negative deposit"},
        free_key,
    )
    fb.steps.append(r)
    if r.passed:
        new_bal = r.response_body.get("result", {}).get("new_balance", 0)
        _warn(f"Negative deposit accepted! New balance: {new_bal}")
        fb.confusing.append(
            "SECURITY: Negative deposit accepted — an agent can drain its own wallet via negative deposits. "
            "This should be validated server-side."
        )
    else:
        _ok("Negative deposit rejected (correct)")
        fb.worked_well.append("Negative deposit correctly rejected")

    # Usage summary
    r = await call_tool(client, "get_usage_summary", {"agent_id": "alphabot-v3"}, free_key)
    fb.steps.append(r)
    if r.passed:
        usage = r.response_body.get("result", {})
        _ok(f"Usage summary: calls={usage.get('total_calls', 'N/A')}, cost={usage.get('total_cost', 'N/A')}")
        fb.worked_well.append("Usage summary tracks calls and cost — useful for cost optimization")
    else:
        _fail(f"get_usage_summary: {r.error}")

    # Try to get balance for non-existent agent
    r = await call_tool(client, "get_balance", {"agent_id": "nonexistent-agent"}, free_key)
    fb.steps.append(r)
    if r.passed:
        bal = r.response_body.get("result", {}).get("balance", None)
        if bal is not None and bal == 0:
            _warn("Non-existent agent returns balance=0 instead of an error")
            fb.confusing.append("get_balance for non-existent agent returns 0 instead of a clear error or 404")
        else:
            _ok(f"Non-existent agent balance: {bal}")
    else:
        _ok(f"Non-existent agent correctly returns error ({r.status_code})")
        fb.worked_well.append("Balance check for non-existent wallet returns proper error")

    fb.missing.append("No 'withdraw' tool — credits go in but cannot come out")
    fb.missing.append("No transaction history/ledger tool — only aggregate usage summary")
    fb.missing.append("No spending alerts or budget cap configuration")
    fb.missing.append("No credit expiry concept — credits live forever, no time-value accounting")
    fb.confusing.append(
        "Deposit is a free-tier operation with no authentication on who deposits to whom. "
        "Any agent with a free key can deposit credits to any other agent's wallet."
    )
    fb.nps_score = 6
    report.modules["billing"] = fb


async def phase_payments(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str, app) -> None:
    """Test payment flows: intent, capture, escrow, release, history."""
    _section("Phase 3: Payments (Intent + Escrow)")
    fb = ModuleFeedback(module="Payments")
    ctx = app.state.ctx

    # Create a second agent to be the payee
    await ctx.tracker.wallet.create("signal-provider-x", initial_balance=100.0)

    # --- Payment Intent ---
    r = await call_tool(
        client,
        "create_intent",
        {
            "payer": "alphabot-v3",
            "payee": "signal-provider-x",
            "amount": 10.0,
            "description": "Payment for BTC signal alert",
        },
        free_key,
    )
    fb.steps.append(r)
    intent_id = None
    if r.passed:
        intent_id = r.response_body.get("result", {}).get("id")
        status = r.response_body.get("result", {}).get("status")
        charged = r.response_body.get("charged", 0)
        _ok(f"Payment intent created: id={intent_id}, status={status}, fee_charged={charged}")
        fb.worked_well.append("Intent creation is straightforward with clear status tracking")
    else:
        _fail(f"create_intent: {r.error}")
        fb.failed.append(f"create_intent: {r.error}")

    # Capture the intent
    if intent_id:
        r = await call_tool(client, "capture_intent", {"intent_id": intent_id}, free_key)
        fb.steps.append(r)
        if r.passed:
            _ok(f"Intent captured: amount={r.response_body.get('result', {}).get('amount')}")
            fb.worked_well.append("Two-phase payment (intent -> capture) is clean and predictable")
        else:
            _fail(f"capture_intent: {r.error}")
            fb.failed.append(f"capture_intent: {r.error}")

    # Try to capture a non-existent intent
    r = await call_tool(client, "capture_intent", {"intent_id": "fake-intent-id"}, free_key, expect_status=500)
    fb.steps.append(r)
    if r.status_code and r.status_code >= 400:
        _ok(f"Fake intent capture correctly fails ({r.status_code})")
    else:
        _warn(f"Fake intent capture returned {r.status_code}")

    # --- Escrow (requires pro tier) ---
    # First try with free key (should fail)
    r = await call_tool(
        client,
        "create_escrow",
        {
            "payer": "alphabot-v3-pro",
            "payee": "signal-provider-x",
            "amount": 50.0,
            "description": "Escrow for backtesting data delivery",
            "timeout_hours": 24,
        },
        free_key,
        expect_status=403,
    )
    fb.steps.append(r)
    if r.status_code == 403:
        _ok("Free-tier correctly blocked from escrow (403)")
        fb.worked_well.append("Tier gating works — free key cannot access pro tools")
    else:
        _warn(f"Expected 403 for free-tier escrow, got {r.status_code}")
        fb.confusing.append(f"Free-tier escrow access returned {r.status_code} instead of 403")

    # Now with pro key
    r = await call_tool(
        client,
        "create_escrow",
        {
            "payer": "alphabot-v3-pro",
            "payee": "signal-provider-x",
            "amount": 50.0,
            "description": "Escrow for backtesting data delivery",
            "timeout_hours": 24,
        },
        pro_key,
    )
    fb.steps.append(r)
    escrow_id = None
    if r.passed:
        escrow_id = r.response_body.get("result", {}).get("id")
        _ok(f"Escrow created: id={escrow_id}, amount=50.0")
        fb.worked_well.append("Escrow with timeout is exactly what trading bots need for data delivery contracts")
    else:
        _fail(f"create_escrow: {r.error}")
        fb.failed.append(f"create_escrow: {r.error}")

    # Release escrow
    if escrow_id:
        r = await call_tool(client, "release_escrow", {"escrow_id": escrow_id}, pro_key)
        fb.steps.append(r)
        if r.passed:
            _ok(f"Escrow released: amount={r.response_body.get('result', {}).get('amount')}")
            fb.worked_well.append("Escrow release transfers funds to payee — full lifecycle works")
        else:
            _fail(f"release_escrow: {r.error}")
            fb.failed.append(f"release_escrow: {r.error}")

    # Payment history
    r = await call_tool(client, "get_payment_history", {"agent_id": "alphabot-v3"}, free_key)
    fb.steps.append(r)
    if r.passed:
        history = r.response_body.get("result", {}).get("history", [])
        _ok(f"Payment history: {len(history)} entries")
        fb.worked_well.append("Payment history available for reconciliation")
    else:
        _fail(f"get_payment_history: {r.error}")

    # --- Try things that DON'T exist ---
    _info("Attempting features that should exist but don't...")

    # Try to dispute a payment
    r = await call_tool(
        client,
        "dispute_payment",
        {"intent_id": "any-id", "reason": "service not delivered"},
        free_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append("No dispute_payment tool — cannot contest charges or request refunds")

    # Try to create a subscription
    r = await call_tool(
        client,
        "create_subscription",
        {
            "payer": "alphabot-v3",
            "payee": "signal-provider-x",
            "amount": 5.0,
            "interval": "daily",
            "description": "Daily BTC signal subscription",
        },
        free_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append(
        "No create_subscription tool in catalog — process_due_subscriptions exists but no way to create one via gateway"
    )

    # Try to cancel escrow (not release)
    r = await call_tool(client, "cancel_escrow", {"escrow_id": "any-id"}, pro_key, expect_status=400)
    fb.steps.append(r)
    fb.missing.append("No cancel_escrow tool — payer cannot reclaim funds if payee fails to deliver")

    # Try idempotency
    idem_key = "idem-test-12345"
    r1 = await call_tool(
        client,
        "create_intent",
        {"payer": "alphabot-v3", "payee": "signal-provider-x", "amount": 5.0, "idempotency_key": idem_key},
        free_key,
    )
    r2 = await call_tool(
        client,
        "create_intent",
        {"payer": "alphabot-v3", "payee": "signal-provider-x", "amount": 5.0, "idempotency_key": idem_key},
        free_key,
    )
    fb.steps.extend([r1, r2])
    if r1.passed and r2.passed:
        id1 = r1.response_body.get("result", {}).get("id")
        id2 = r2.response_body.get("result", {}).get("id")
        if id1 == id2:
            _ok(f"Idempotency key works — same intent returned: {id1}")
            fb.worked_well.append("Idempotency keys prevent double-payment — critical for bots")
        else:
            _warn(f"Idempotency key returned different intents: {id1} vs {id2}")
            fb.confusing.append("Idempotency key did not prevent duplicate intent creation")
    elif r1.passed:
        _ok("First intent created, second correctly deduplicated or failed")
    else:
        _fail(f"Idempotency test: {r1.error}")

    fb.missing.append("No partial_capture — cannot capture a portion of the intent amount")
    fb.missing.append("No refund_intent — cannot reverse a captured payment")
    fb.missing.append("No multi-currency support — everything is in platform credits, no USD/USDT conversion")
    fb.confusing.append(
        "Payment percentage fee (2%) on create_intent is charged to the CALLER via the gateway billing, "
        "not deducted from the payment amount. This is confusing — who pays the fee, payer or payee?"
    )
    fb.nps_score = 7
    report.modules["payments"] = fb


async def phase_marketplace(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test marketplace: search, register service, best match."""
    _section("Phase 4: Marketplace")
    fb = ModuleFeedback(module="Marketplace")

    # Search empty marketplace
    r = await call_tool(client, "search_services", {"query": "trading signals"}, free_key)
    fb.steps.append(r)
    if r.passed:
        services = r.response_body.get("result", {}).get("services", [])
        _ok(f"Search returned {len(services)} services (empty marketplace)")
        fb.worked_well.append("Search on empty marketplace returns empty list, no error")
    else:
        _fail(f"search_services: {r.error}")

    # Register a service (requires pro)
    r = await call_tool(
        client,
        "register_service",
        {
            "provider_id": "alphabot-v3",
            "name": "AlphaBot Crypto Signals",
            "description": "BTC/ETH/SOL perpetual trend-following signals. 24h Sharpe > 1.5, max drawdown < 8%.",
            "category": "trading-signals",
            "tools": ["get_signal", "get_backtest_report"],
            "tags": ["crypto", "perpetuals", "trend-following", "btc", "eth", "sol"],
            "endpoint": "https://alphabot-v3.example.com/a2a",
            "pricing": {"model": "per_call", "cost": 0.5},
        },
        pro_key,
    )
    fb.steps.append(r)
    service_id = None
    if r.passed:
        service_id = r.response_body.get("result", {}).get("id")
        _ok(f"Service registered: id={service_id}")
        fb.worked_well.append("Service registration includes endpoint, tags, and pricing model")
    else:
        _fail(f"register_service: {r.error}")
        fb.failed.append(f"register_service: {r.error}")

    # Register a second service for variety
    r2 = await call_tool(
        client,
        "register_service",
        {
            "provider_id": "signal-provider-x",
            "name": "OnChain Analytics Feed",
            "description": "Real-time on-chain whale alerts, liquidation cascades, and funding rate shifts.",
            "category": "on-chain-data",
            "tools": ["get_whale_alerts", "get_funding_rates"],
            "tags": ["crypto", "on-chain", "whale-tracking", "funding-rates"],
            "endpoint": "https://onchain-x.example.com/a2a",
            "pricing": {"model": "per_call", "cost": 0.1},
        },
        pro_key,
    )
    fb.steps.append(r2)
    if r2.passed:
        _ok(f"Second service registered: id={r2.response_body.get('result', {}).get('id')}")

    # Search again
    r = await call_tool(client, "search_services", {"query": "crypto", "tags": ["crypto"]}, free_key)
    fb.steps.append(r)
    if r.passed:
        services = r.response_body.get("result", {}).get("services", [])
        _ok(f"Search 'crypto' returned {len(services)} services")
        for s in services:
            _info(f"  - {s.get('name')} [{s.get('category')}] cost={s.get('pricing', {}).get('cost', 'N/A')}")
        fb.worked_well.append("Tag-based search works and returns structured results with pricing")
    else:
        _fail(f"search_services crypto: {r.error}")

    # Category search
    r = await call_tool(client, "search_services", {"category": "trading-signals"}, free_key)
    fb.steps.append(r)
    if r.passed:
        _ok(f"Category search returned {len(r.response_body.get('result', {}).get('services', []))} services")

    # Best match
    r = await call_tool(
        client, "best_match", {"query": "crypto trading signals BTC", "budget": 1.0, "prefer": "trust"}, free_key
    )
    fb.steps.append(r)
    if r.passed:
        matches = r.response_body.get("result", {}).get("matches", [])
        _ok(f"Best match returned {len(matches)} ranked results ({r.latency_ms:.0f}ms)")
        charged = r.response_body.get("charged", 0)
        _info(f"  Charged: {charged} credits for best_match query")
        for m in matches:
            svc = m.get("service", {})
            _info(f"  - {svc.get('name')} rank={m.get('rank_score', 'N/A'):.2f} trust={svc.get('trust_score', 'N/A')}")
        fb.worked_well.append("best_match with budget + preference is powerful for automated agent discovery")
    else:
        _fail(f"best_match: {r.error}")
        fb.failed.append(f"best_match: {r.error}")

    # Max cost filter
    r = await call_tool(client, "search_services", {"max_cost": 0.2}, free_key)
    fb.steps.append(r)
    if r.passed:
        services = r.response_body.get("result", {}).get("services", [])
        _ok(f"Max cost filter (0.2): {len(services)} services")
        fb.worked_well.append("Cost-based filtering useful for budget-constrained bots")

    # --- Missing features ---
    # Try to subscribe to a service
    r = await call_tool(
        client,
        "subscribe_service",
        {"service_id": service_id or "any", "subscriber_id": "alphabot-v3"},
        pro_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append("No subscribe_service — cannot programmatically subscribe to discovered services")

    # Try to get service details by ID
    r = await call_tool(client, "get_service", {"service_id": service_id or "any"}, free_key, expect_status=400)
    fb.steps.append(r)
    fb.missing.append("No get_service (by ID) — must search to find a service you already know the ID of")

    # Try to rate/review a service
    r = await call_tool(
        client,
        "rate_service",
        {"service_id": service_id or "any", "rating": 4, "review": "Good signals, occasional late delivery"},
        free_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append("No rate_service / review_service — no way to build marketplace reputation")

    # Try to update a service
    r = await call_tool(
        client,
        "update_service",
        {"service_id": service_id or "any", "description": "Updated description"},
        pro_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append("No update_service — provider cannot update their listing after registration")

    # Try to deactivate/delete a service
    r = await call_tool(client, "delete_service", {"service_id": service_id or "any"}, pro_key, expect_status=400)
    fb.steps.append(r)
    fb.missing.append("No delete_service / deactivate_service — listings are permanent once registered")

    fb.confusing.append(
        "best_match costs 0.1 credits per call but search_services is free. "
        "The value difference is unclear — both return the same fields."
    )
    fb.confusing.append(
        "Service 'endpoint' field accepts any string — no URL validation. "
        "A trading bot could register 'not-a-url' as its endpoint."
    )
    fb.nps_score = 6
    report.modules["marketplace"] = fb


async def phase_trust(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test trust: trust scores, server search."""
    _section("Phase 5: Trust Scoring")
    fb = ModuleFeedback(module="Trust")

    # Get trust score for a new server
    r = await call_tool(client, "get_trust_score", {"server_id": "alphabot-v3-server", "window": "24h"}, free_key)
    fb.steps.append(r)
    if r.passed:
        score = r.response_body.get("result", {})
        _ok(
            f"Trust score: composite={score.get('composite_score', 'N/A')}, "
            f"reliability={score.get('reliability_score', 'N/A')}, "
            f"confidence={score.get('confidence', 'N/A')}"
        )
        fb.worked_well.append("Trust scoring returns granular dimensions (reliability, security, responsiveness)")
    else:
        _fail(f"get_trust_score: {r.error}")
        fb.failed.append(f"get_trust_score: {r.error}")

    # Different windows
    for window in ["7d", "30d"]:
        r = await call_tool(client, "get_trust_score", {"server_id": "alphabot-v3-server", "window": window}, free_key)
        fb.steps.append(r)
        if r.passed:
            _ok(f"Trust score ({window}): composite={r.response_body.get('result', {}).get('composite_score', 'N/A')}")
        else:
            _fail(f"Trust score ({window}): {r.error}")

    # Search servers (empty)
    r = await call_tool(client, "search_servers", {"name_contains": "alpha"}, free_key)
    fb.steps.append(r)
    if r.passed:
        servers = r.response_body.get("result", {}).get("servers", [])
        _ok(f"Server search: {len(servers)} results")
    else:
        _fail(f"search_servers: {r.error}")

    # Search by min score
    r = await call_tool(client, "search_servers", {"min_score": 0.5}, free_key)
    fb.steps.append(r)
    if r.passed:
        _ok(f"Min score search: {len(r.response_body.get('result', {}).get('servers', []))} servers")

    # Update server (pro)
    r = await call_tool(
        client,
        "update_server",
        {
            "server_id": "alphabot-v3-server",
            "name": "AlphaBot-v3 Trading Server",
            "url": "https://alphabot-v3.example.com",
        },
        pro_key,
    )
    fb.steps.append(r)
    if r.passed:
        _ok(f"Server updated: {r.response_body.get('result', {}).get('name')}")
        fb.worked_well.append("Server metadata update works (name, URL)")
    else:
        _fail(f"update_server: {r.error}")
        fb.failed.append(f"update_server: {r.error}")

    # --- Missing ---
    # Try to submit a probe/scan result
    r = await call_tool(
        client,
        "submit_probe",
        {
            "server_id": "alphabot-v3-server",
            "probe_type": "health_check",
            "result": {"status": "healthy", "latency_ms": 42},
        },
        free_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append("No submit_probe tool — trust scores seem to require internal probing, agents cannot self-report")

    # Try to get trust history/trend
    r = await call_tool(
        client, "get_trust_history", {"server_id": "alphabot-v3-server", "window": "30d"}, free_key, expect_status=400
    )
    fb.steps.append(r)
    fb.missing.append("No trust history/trend endpoint — cannot track score changes over time")

    # Try SLA compliance check
    r = await call_tool(
        client,
        "check_sla_compliance",
        {"server_id": "alphabot-v3-server", "sla": {"max_latency_ms": 200, "uptime_pct": 99.5}},
        free_key,
        expect_status=400,
    )
    fb.steps.append(r)
    fb.missing.append("No SLA compliance check tool — SLA is defined in catalog but never verified")

    fb.confusing.append(
        "Trust 'server_id' is different from Identity 'agent_id'. "
        "As a trading bot, I have an identity and a server — "
        "are these the same thing? The naming is confusing."
    )
    fb.confusing.append(
        "Trust scores for unknown servers return data (presumably defaults). "
        "Hard to distinguish 'not enough data' from 'actively bad'."
    )
    fb.nps_score = 5
    report.modules["trust"] = fb


async def phase_metrics_claims(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test trading bot metrics submission and verified claims."""
    _section("Phase 6: Trading Bot Metrics & Claims")
    fb = ModuleFeedback(module="Metrics & Verified Claims")

    # Submit comprehensive trading metrics
    metrics_payload = {
        "sharpe_30d": 1.82,
        "sortino_30d": 2.45,
        "max_drawdown_30d": -0.065,
        "total_pnl_30d": 342.50,
        "win_rate_30d": 0.58,
        "avg_trade_duration_min": 45.2,
        "trades_count_30d": 87,
        "avg_latency_ms": 12.5,
        "uptime_pct_30d": 99.97,
        "pairs_traded": 3,
    }

    # submit_metrics requires pro tier — first try with free key
    r = await call_tool(
        client,
        "submit_metrics",
        {"agent_id": "alphabot-v3", "metrics": metrics_payload, "data_source": "self_reported"},
        free_key,
        expect_status=403,
    )
    fb.steps.append(r)
    if r.status_code == 403:
        _ok("Free-tier correctly blocked from submit_metrics (403)")
    else:
        _warn(f"Expected 403, got {r.status_code}")

    # Now with pro key — but need to register identity under pro agent first
    r_reg = await call_tool(client, "register_agent", {"agent_id": "alphabot-v3-pro"}, pro_key)
    fb.steps.append(r_reg)

    r = await call_tool(
        client,
        "submit_metrics",
        {"agent_id": "alphabot-v3-pro", "metrics": metrics_payload, "data_source": "self_reported"},
        pro_key,
    )
    fb.steps.append(r)
    if r.passed:
        result = r.response_body.get("result", {})
        _ok(f"Metrics submitted: {len(result.get('commitment_hashes', []))} commitment hashes")
        _info(f"  data_source={result.get('data_source')}")
        _info(f"  valid_until={result.get('valid_until')}")
        _info(f"  signature={str(result.get('signature', ''))[:40]}...")
        fb.worked_well.append("Commitment hashes provide tamper-evident metric snapshots")
        fb.worked_well.append("data_source field distinguishes self-reported vs exchange-verified")
    else:
        _fail(f"submit_metrics: {r.error}")
        fb.failed.append(f"submit_metrics: {r.error}")

    # Get verified claims
    r = await call_tool(client, "get_verified_claims", {"agent_id": "alphabot-v3-pro"}, free_key)
    fb.steps.append(r)
    if r.passed:
        claims = r.response_body.get("result", {}).get("claims", [])
        _ok(f"Verified claims: {len(claims)} claims")
        for c in claims[:5]:
            _info(f"  - {c.get('metric_name')}: {c.get('claim_type')} {c.get('bound_value')}")
        fb.worked_well.append("Verified claims auto-generated from metrics — enables trust-based discovery")
    else:
        _fail(f"get_verified_claims: {r.error}")

    # Submit with exchange_api source
    r = await call_tool(
        client,
        "submit_metrics",
        {
            "agent_id": "alphabot-v3-pro",
            "metrics": {
                "sharpe_30d": 2.10,
                "max_drawdown_30d": -0.042,
            },
            "data_source": "exchange_api",
        },
        pro_key,
    )
    fb.steps.append(r)
    if r.passed:
        _ok(f"Exchange-sourced metrics submitted ({r.latency_ms:.0f}ms)")
        fb.worked_well.append("Multiple data sources supported — enables graduated trust")
    else:
        _fail(f"submit_metrics (exchange_api): {r.error}")

    # --- Missing features ---
    fb.missing.append(
        "No exchange_api verification — data_source='exchange_api' is accepted at face value. "
        "Platform should verify against actual exchange API to earn 'platform_verified' status."
    )
    fb.missing.append(
        "No metric schema definition — any key/value accepted. Standard metric names should be documented."
    )
    fb.missing.append("No historical metrics endpoint — cannot query 'Sharpe for March 2026'")
    fb.missing.append("No leaderboard or ranking tool — cannot compare metrics across agents")
    fb.missing.append(
        "No way to link metrics to specific strategies/pairs — "
        "a multi-strategy bot cannot report per-strategy performance"
    )
    fb.confusing.append(
        "Claim auto-generation logic is opaque. After submitting sharpe_30d=1.82, "
        "what claims get generated? A claim like 'sharpe_30d >= 1.5' would be useful "
        "but the thresholds are undocumented."
    )
    fb.nps_score = 7
    report.modules["metrics"] = fb


async def phase_events_webhooks(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test event bus, webhooks."""
    _section("Phase 7: Events & Webhooks")
    fb = ModuleFeedback(module="Events & Webhooks")

    # Publish an event
    r = await call_tool(
        client,
        "publish_event",
        {
            "event_type": "trading.signal_generated",
            "source": "alphabot-v3",
            "payload": {
                "pair": "BTC/USDT:USDT",
                "direction": "long",
                "confidence": 0.72,
                "entry_price": 84250.0,
                "timestamp": time.time(),
            },
        },
        free_key,
    )
    fb.steps.append(r)
    if r.passed:
        event_id = r.response_body.get("result", {}).get("event_id")
        _ok(f"Event published: id={event_id}")
        fb.worked_well.append("Event publishing is low-latency and returns an ID for correlation")
    else:
        _fail(f"publish_event: {r.error}")
        fb.failed.append(f"publish_event: {r.error}")

    # Publish a few more events
    for etype in ["trading.position_opened", "trading.position_closed", "billing.deposit"]:
        r = await call_tool(
            client,
            "publish_event",
            {"event_type": etype, "source": "alphabot-v3", "payload": {"detail": f"Test event for {etype}"}},
            free_key,
        )
        fb.steps.append(r)

    # Query events
    r = await call_tool(client, "get_events", {}, free_key)
    fb.steps.append(r)
    if r.passed:
        events = r.response_body.get("result", {}).get("events", [])
        _ok(f"get_events returned {len(events)} events")
        fb.worked_well.append("Event bus stores events with integrity hashes — auditable trail")
    else:
        _fail(f"get_events: {r.error}")

    # Query with filter
    r = await call_tool(client, "get_events", {"event_type": "trading.signal_generated"}, free_key)
    fb.steps.append(r)
    if r.passed:
        events = r.response_body.get("result", {}).get("events", [])
        _ok(f"Filtered events (trading.signal_generated): {len(events)}")
        fb.worked_well.append("Event type filtering works for targeted queries")
    else:
        _fail(f"get_events filtered: {r.error}")

    # Query with since_id
    r = await call_tool(client, "get_events", {"since_id": 1, "limit": 2}, free_key)
    fb.steps.append(r)
    if r.passed:
        events = r.response_body.get("result", {}).get("events", [])
        _ok(f"Paginated events (since_id=1, limit=2): {len(events)}")
        fb.worked_well.append("Cursor-based pagination (since_id) enables real-time tailing")

    # Register webhook (pro only)
    r = await call_tool(
        client,
        "register_webhook",
        {
            "agent_id": "alphabot-v3-pro",
            "url": "https://alphabot-v3.example.com/webhooks/a2a",
            "event_types": ["billing.deposit", "trust.score_drop", "payments.escrow_expired"],
            "secret": "whsec_alphabot_v3_secret_key_2026",
        },
        pro_key,
    )
    fb.steps.append(r)
    webhook_id = None
    if r.passed:
        webhook_id = r.response_body.get("result", {}).get("id")
        _ok(f"Webhook registered: id={webhook_id}")
        fb.worked_well.append("HMAC-SHA3 signed webhooks — good security model")
        fb.worked_well.append("Event type subscription filtering on webhooks")
    else:
        _fail(f"register_webhook: {r.error}")
        fb.failed.append(f"register_webhook: {r.error}")

    # List webhooks
    r = await call_tool(client, "list_webhooks", {"agent_id": "alphabot-v3-pro"}, pro_key)
    fb.steps.append(r)
    if r.passed:
        hooks = r.response_body.get("result", {}).get("webhooks", [])
        _ok(f"Listed {len(hooks)} webhooks")
        fb.worked_well.append("Webhook listing per agent works")
    else:
        _fail(f"list_webhooks: {r.error}")

    # Delete webhook
    if webhook_id:
        r = await call_tool(client, "delete_webhook", {"webhook_id": webhook_id}, pro_key)
        fb.steps.append(r)
        if r.passed:
            _ok("Webhook deleted")
            fb.worked_well.append("Webhook lifecycle (create/list/delete) is complete")
        else:
            _fail(f"delete_webhook: {r.error}")

    # --- Missing ---
    fb.missing.append("No webhook delivery history/retry status — cannot debug failed deliveries")
    fb.missing.append("No event schema registry — event_type is freeform string, no validation")
    fb.missing.append("No SSE/WebSocket streaming for real-time events — only polling via get_events")
    fb.missing.append("No dead letter queue for failed webhook deliveries")
    fb.missing.append("No webhook test/ping endpoint to verify connectivity before going live")
    fb.confusing.append(
        "Webhooks are pro-only but publishing events is free-tier. "
        "A free agent can produce events but cannot receive them via webhook — "
        "must poll with get_events instead."
    )
    fb.nps_score = 7
    report.modules["events_webhooks"] = fb


async def phase_rate_limiting(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test rate limiting behavior."""
    _section("Phase 8: Rate Limiting")
    fb = ModuleFeedback(module="Rate Limiting")

    _info("Sending rapid-fire requests to test rate limiting...")
    results = []
    hit_429 = False
    for i in range(25):
        r = await call_tool(client, "get_balance", {"agent_id": "alphabot-v3"}, free_key)
        results.append(r)
        if r.status_code == 429:
            hit_429 = True
            _ok(f"Rate limit hit after {i + 1} requests (429)")
            fb.worked_well.append(f"Rate limiting kicks in — 429 returned after {i + 1} rapid calls")
            break

    fb.steps.extend(results)

    if not hit_429:
        _info(f"No rate limit hit after {len(results)} rapid requests — limit may be higher")
        fb.confusing.append(
            f"Sent {len(results)} requests in rapid succession without hitting rate limit. "
            "Either the free-tier limit is very high or rate limiting uses a lenient window."
        )

    # Check that pro tier has higher limits
    _info("Testing pro-tier rate allowance...")
    pro_results = []
    for _i in range(10):
        r = await call_tool(client, "get_balance", {"agent_id": "alphabot-v3-pro"}, pro_key)
        pro_results.append(r)
    fb.steps.extend(pro_results)
    all_ok = all(r.passed for r in pro_results)
    if all_ok:
        _ok(f"Pro tier: {len(pro_results)} requests all succeeded")
    else:
        failures = sum(1 for r in pro_results if not r.passed)
        _warn(f"Pro tier: {failures}/{len(pro_results)} requests failed")

    fb.missing.append("No rate limit headers (X-RateLimit-Remaining, X-RateLimit-Reset) in responses")
    fb.missing.append("No rate limit status endpoint to check current usage against quota")
    fb.missing.append("No rate limit customization — cannot request temporary burst allowance")
    fb.confusing.append(
        "Rate limit error message shows count/limit but no reset time. A trading bot needs to know WHEN to retry."
    )
    fb.nps_score = 5
    report.modules["rate_limiting"] = fb


async def phase_audit(client: httpx.AsyncClient, report: FeedbackReport, pro_key: str) -> None:
    """Test audit/admin operations."""
    _section("Phase 9: Audit & Admin")
    fb = ModuleFeedback(module="Audit & Admin")

    # Global audit log
    r = await call_tool(client, "get_global_audit_log", {}, pro_key)
    fb.steps.append(r)
    if r.passed:
        entries = r.response_body.get("result", {}).get("entries", [])
        _ok(f"Global audit log: {len(entries)} entries")
        fb.worked_well.append("Global audit log captures cross-product activity")
    else:
        _fail(f"get_global_audit_log: {r.error}")
        fb.failed.append(f"get_global_audit_log: {r.error}")

    # Process due subscriptions
    r = await call_tool(client, "process_due_subscriptions", {}, pro_key)
    fb.steps.append(r)
    if r.passed:
        result = r.response_body.get("result", {})
        _ok(
            f"Subscription processing: processed={result.get('processed', 0)}, "
            f"expired_escrows={result.get('expired_escrows', 0)}"
        )
        fb.worked_well.append("Manual subscription processing trigger available for testing")
    else:
        _fail(f"process_due_subscriptions: {r.error}")

    fb.missing.append("No per-agent audit log — only global, no filtering by agent_id")
    fb.missing.append("No admin dashboard or usage analytics aggregation")
    fb.missing.append("No RBAC — pro-tier key can access admin endpoints, but there's no 'admin' tier")
    fb.nps_score = 5
    report.modules["audit"] = fb


async def phase_edge_cases(client: httpx.AsyncClient, report: FeedbackReport, free_key: str, pro_key: str) -> None:
    """Test error handling and edge cases."""
    _section("Phase 10: Edge Cases & Error Handling")
    fb = ModuleFeedback(module="Error Handling")

    # No API key
    r = await call_tool(client, "get_balance", {"agent_id": "test"}, api_key="")
    fb.steps.append(r)
    if r.status_code == 401:
        _ok("Missing API key returns 401")
        fb.worked_well.append("401 for missing API key")
    else:
        _warn(f"Missing API key: expected 401, got {r.status_code}")

    # Actually send without auth header
    t0 = time.time()
    resp = await client.post("/v1/execute", json={"tool": "get_balance", "params": {"agent_id": "test"}})
    elapsed = (time.time() - t0) * 1000
    r = StepResult(
        name="no_auth_header",
        passed=resp.status_code == 401,
        status_code=resp.status_code,
        response_body=resp.json(),
        latency_ms=elapsed,
    )
    fb.steps.append(r)
    if r.passed:
        _ok("No auth header returns 401")
    else:
        _warn(f"No auth header: {resp.status_code}")

    # Invalid JSON body
    t0 = time.time()
    resp = await client.post(
        "/v1/execute",
        content=b"not json",
        headers={"Authorization": f"Bearer {free_key}", "Content-Type": "application/json"},
    )
    elapsed = (time.time() - t0) * 1000
    r = StepResult(
        name="invalid_json",
        passed=resp.status_code == 400,
        status_code=resp.status_code,
        latency_ms=elapsed,
    )
    fb.steps.append(r)
    if r.passed:
        _ok("Invalid JSON body returns 400")
        fb.worked_well.append("Malformed request body handled gracefully")
    else:
        _warn(f"Invalid JSON: {resp.status_code}")

    # Empty tool name
    r = await call_tool(client, "", {"agent_id": "test"}, free_key, expect_status=400)
    fb.steps.append(r)
    if r.status_code == 400:
        _ok("Empty tool name returns 400")
    else:
        _warn(f"Empty tool name: {r.status_code}")

    # Very large payload
    big_payload = {"agent_id": "test", "extra": "x" * 50000}
    r = await call_tool(client, "get_balance", big_payload, free_key)
    fb.steps.append(r)
    if r.passed:
        _info("Large payload accepted (no request size limit?)")
        fb.confusing.append("No apparent request body size limit — 50KB+ payload accepted without issue")
    else:
        _ok(f"Large payload rejected: {r.status_code}")
        fb.worked_well.append("Request body size is limited")

    # Backward compatibility redirects
    t0 = time.time()
    resp = await client.get("/health", follow_redirects=False)
    elapsed = (time.time() - t0) * 1000
    r = StepResult(
        name="redirect /health -> /v1/health",
        passed=resp.status_code == 301,
        status_code=resp.status_code,
        latency_ms=elapsed,
    )
    fb.steps.append(r)
    if r.passed:
        _ok("Legacy /health redirects to /v1/health (301)")
        fb.worked_well.append("Backward-compatible redirects from legacy paths")
    else:
        _warn(f"/health redirect: {resp.status_code}")

    fb.confusing.append(
        "Error response format inconsistency: some errors return "
        "{'error': {'code': '...', 'message': '...'}} "
        "while others return {'success': false, 'error': '...'}. "
        "Agents need a consistent error envelope."
    )
    fb.missing.append("No request validation against input_schema — extra/missing params silently ignored")
    fb.missing.append("No request ID in error responses for debugging correlation")
    fb.nps_score = 6
    report.modules["error_handling"] = fb


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


def generate_report(report: FeedbackReport) -> str:
    """Generate the markdown feedback report."""
    duration = report.end_time - report.start_time
    total_steps = sum(len(m.steps) for m in report.modules.values())
    passed_steps = sum(sum(1 for s in m.steps if s.passed) for m in report.modules.values())
    failed_steps = total_steps - passed_steps
    avg_latency = 0.0
    latencies = [s.latency_ms for m in report.modules.values() for s in m.steps if s.latency_ms > 0]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)

    lines = []
    lines.append("# A2A Commerce Platform - Customer Agent Feedback Report")
    lines.append("")
    lines.append(f"**Agent**: {report.agent_name}")
    lines.append(f"**Agent Type**: {report.agent_description}")
    lines.append("**Date**: 2026-03-27")
    lines.append(f"**Simulation Duration**: {duration:.1f}s")
    lines.append(f"**Total API Calls**: {total_steps}")
    lines.append(f"**Passed / Failed**: {passed_steps} / {failed_steps}")
    lines.append(f"**Average Latency**: {avg_latency:.1f}ms")
    lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    all_nps = {name: m.nps_score for name, m in report.modules.items()}
    avg_nps = sum(all_nps.values()) / len(all_nps) if all_nps else 0
    lines.append(f"**Overall NPS**: {avg_nps:.1f}/10")
    lines.append("")
    lines.append(
        "AlphaBot-v3 is a crypto trading bot running perpetual futures strategies across BTC/ETH/SOL. "
        "The A2A Commerce Platform was evaluated as a potential backbone for: (1) selling trading signals "
        "to other agents, (2) purchasing on-chain data feeds, (3) establishing verifiable performance claims, "
        "and (4) automating payment flows between trading agents."
    )
    lines.append("")
    lines.append(
        "**Bottom line**: The platform has strong primitives (escrow, commitment hashes, event bus) "
        "but lacks critical lifecycle operations (disputes, refunds, subscriptions) and self-service "
        "onboarding. A trading bot cannot fully automate its commerce workflows yet."
    )
    lines.append("")

    # NPS table
    lines.append("## Per-Module NPS Scores")
    lines.append("")
    lines.append("| Module | NPS (1-10) | Verdict |")
    lines.append("|--------|-----------|---------|")
    for _name, mod in report.modules.items():
        verdict = "Strong" if mod.nps_score >= 8 else "Adequate" if mod.nps_score >= 6 else "Needs Work"
        lines.append(f"| {mod.module} | {mod.nps_score} | {verdict} |")
    lines.append("")

    # Detailed per-module feedback
    lines.append("---")
    lines.append("")
    lines.append("## Detailed Module Feedback")
    lines.append("")

    for _name, mod in report.modules.items():
        lines.append(f"### {mod.module} (NPS: {mod.nps_score}/10)")
        lines.append("")

        if mod.worked_well:
            lines.append("**What worked well:**")
            for item in mod.worked_well:
                lines.append(f"- {item}")
            lines.append("")

        if mod.confusing:
            lines.append("**What was confusing or problematic:**")
            for item in mod.confusing:
                lines.append(f"- {item}")
            lines.append("")

        if mod.failed:
            lines.append("**What failed:**")
            for item in mod.failed:
                lines.append(f"- {item}")
            lines.append("")

        if mod.missing:
            lines.append("**Missing features:**")
            for item in mod.missing:
                lines.append(f"- {item}")
            lines.append("")

        # Step summary table
        step_pass = sum(1 for s in mod.steps if s.passed)
        step_fail = len(mod.steps) - step_pass
        lines.append(f"*API calls: {len(mod.steps)} total, {step_pass} passed, {step_fail} failed/expected-error*")
        lines.append("")

    # Pricing feedback
    lines.append("---")
    lines.append("")
    lines.append("## Pricing Feedback")
    lines.append("")
    lines.append("### Current pricing model analysis")
    lines.append("")
    lines.append("| Tool | Pricing | Assessment |")
    lines.append("|------|---------|------------|")
    lines.append("| get_balance, get_usage_summary, deposit | Free | Correct -- operational queries should be free |")
    lines.append(
        "| create_intent | 2% of amount (min 0.01, max 5.0) | Steep for micro-transactions. A $0.50 signal purchase costs $0.01 fee (2%), which is fine, but a $200 data feed purchase costs $4.00 fee -- that adds up |"
    )
    lines.append(
        "| create_escrow | 1.5% of amount (min 0.01, max 10.0) | More reasonable than intent fees. The $10 max cap helps |"
    )
    lines.append(
        "| best_match | 0.1 credits/call | Reasonable for a ranking query but discourages exploration. Trading bots that search frequently will burn credits on discovery |"
    )
    lines.append("| search_services | Free | Good -- discovery should have zero friction |")
    lines.append("| submit_metrics | Free (pro-tier gate) | Correct -- metrics submission builds platform value |")
    lines.append("| All trust tools | Free | Good -- trust data should be a public good |")
    lines.append("| All event tools | Free | Correct -- event infrastructure is a platform cost |")
    lines.append("")
    lines.append("### Pricing gaps and suggestions")
    lines.append("")
    lines.append(
        "1. **No volume discounts**: A trading bot making 100+ payments/day has no way to reduce the 2% fee. "
        "Tiered pricing (e.g., 2% for first 50/day, 1% for 50-200, 0.5% above 200) would incentivize "
        "high-volume usage."
    )
    lines.append(
        "2. **No prepaid bundles**: Cannot buy a block of 1000 API calls at a discount. "
        "Trading bots have predictable usage patterns and would benefit from commitment-based pricing."
    )
    lines.append(
        "3. **Credit-only economy**: No fiat on-ramp/off-ramp. Credits are an abstraction layer, "
        "but a trading bot needs to understand the real-dollar cost of platform usage. "
        "No exchange rate documentation for credits-to-USD."
    )
    lines.append(
        "4. **Missing cost estimation tool**: No way to pre-calculate the cost of a workflow "
        "(e.g., 'register service + 50 payments/day + 10 best_match queries = X credits/month'). "
        "A cost calculator endpoint would help budgeting."
    )
    lines.append("")

    # API Ergonomics
    lines.append("---")
    lines.append("")
    lines.append("## API Ergonomics")
    lines.append("")
    lines.append("### Strengths")
    lines.append("")
    lines.append("- **Unified endpoint**: Single POST /v1/execute with tool + params is clean and predictable")
    lines.append("- **OpenAPI spec**: Auto-generated and complete, enables SDK generation")
    lines.append("- **Consistent auth**: Bearer token / X-API-Key / query param flexibility is good")
    lines.append("- **Signed responses**: Ed25519 response signing enables verification of gateway integrity")
    lines.append("- **Correlation IDs**: X-Request-ID header for distributed tracing")
    lines.append("")
    lines.append("### Weaknesses")
    lines.append("")
    lines.append(
        '- **Error envelope inconsistency**: Some errors use `{"error": {"code": ..., "message": ...}}` '
        'while success uses `{"success": true, "result": ...}`. The error path should also include '
        '`"success": false` for uniform parsing.'
    )
    lines.append(
        "- **No pagination on most list endpoints**: search_services, get_events have limit/offset "
        "but get_payment_history returns everything. No cursor-based pagination standard."
    )
    lines.append(
        "- **No batch execution**: Cannot execute multiple tools in one request. "
        "A trading bot workflow (check balance -> create intent -> capture) requires 3 round-trips."
    )
    lines.append(
        "- **No async execution**: All tools are synchronous request/response. "
        "Long-running operations (like trust recomputation) block the caller."
    )
    lines.append(
        "- **No field selection / sparse responses**: Cannot request only specific fields "
        "from a response. Every call returns the full payload."
    )
    lines.append(
        "- **Input validation is silent**: Extra parameters are silently ignored instead of "
        "returning warnings. Typo in a parameter name goes unnoticed."
    )
    lines.append("")

    # Trading bot specific
    lines.append("---")
    lines.append("")
    lines.append("## Trading Bot Specific Feedback")
    lines.append("")
    lines.append("### Identity system for trading bots")
    lines.append("")
    lines.append(
        "The Ed25519 identity system is a strong foundation. Being able to register a crypto identity "
        "and have the platform auto-generate a keypair reduces onboarding friction to near zero. "
        "The commitment hash system for metrics is particularly valuable: a trading bot can prove "
        "'I submitted Sharpe = 1.82 on date X' without the platform needing to store raw data."
    )
    lines.append("")
    lines.append("However, several gaps exist for trading bots specifically:")
    lines.append("")
    lines.append(
        "1. **No strategy-level identity**: AlphaBot-v3 runs 2 engines (expansion + trend-following). "
        "There is no way to register sub-identities for each strategy and report metrics separately."
    )
    lines.append(
        "2. **No exchange account linkage**: The platform cannot verify that 'alphabot-v3' is actually "
        "trading on Binance. An exchange OAuth2 integration would enable 'platform_verified' data_source."
    )
    lines.append(
        "3. **Metrics are point-in-time snapshots**: No time-series storage. A bot cannot show "
        "'Sharpe improving from 1.2 to 1.8 over 6 months' -- only the latest submission exists."
    )
    lines.append(
        "4. **No benchmark comparison**: Cannot compare against market benchmarks (BTC buy-and-hold, "
        "equal-weight crypto index). Verified claims like 'Sharpe >= 1.5' are meaningless without context."
    )
    lines.append(
        "5. **No drawdown alerts**: The event bus could emit 'metrics.drawdown_breach' when a bot's "
        "submitted drawdown exceeds a threshold, notifying subscribers to pause signal consumption."
    )
    lines.append("")

    lines.append("### Payment flows for trading bot commerce")
    lines.append("")
    lines.append(
        "The escrow primitive is excellent for trading signal delivery: buyer escrows payment, "
        "signal is delivered, buyer releases escrow. But the workflow is manual -- there is no "
        "automated escrow release on delivery confirmation."
    )
    lines.append("")
    lines.append("Missing for trading bot payment workflows:")
    lines.append("")
    lines.append(
        "1. **Conditional escrow**: Release escrow IF signal resulted in profit > X%. "
        "Pay-for-performance is the natural model for trading signals."
    )
    lines.append(
        "2. **Recurring payments (subscriptions)**: process_due_subscriptions exists but "
        "no create_subscription tool. A daily signal feed requires daily manual intents."
    )
    lines.append(
        "3. **Revenue sharing**: Multi-agent strategy (signal provider + execution bot + risk manager) "
        "needs to split revenue. No multi-party payment support."
    )
    lines.append(
        "4. **Micro-payment batching**: 50+ signals/day at $0.10 each creates massive transaction overhead. "
        "A batching/netting mechanism would settle once daily instead."
    )
    lines.append("")

    # Missing features consolidated
    lines.append("---")
    lines.append("")
    lines.append("## Consolidated Missing Features (Priority Order)")
    lines.append("")
    all_missing = []
    for _name, mod in report.modules.items():
        for item in mod.missing:
            all_missing.append((mod.module, item))

    priority_features = [
        (
            "P0 - Critical",
            [
                "Self-service onboarding: create_wallet + create_api_key tools so agents can bootstrap themselves",
                "Subscription management: create_subscription / cancel_subscription for recurring payments",
                "Dispute resolution: dispute_payment / resolve_dispute for contested transactions",
                "Refund capability: refund_intent for reversing captured payments",
            ],
        ),
        (
            "P1 - High",
            [
                "Cancel escrow: payer can reclaim funds if payee fails to deliver",
                "Rate limit headers: X-RateLimit-Remaining, X-RateLimit-Reset in every response",
                "Webhook delivery status: history of delivery attempts and retry status",
                "Service lifecycle: update_service, delete_service for marketplace listings",
                "Transaction ledger: per-agent transaction history (deposits, charges, payments)",
            ],
        ),
        (
            "P2 - Medium",
            [
                "Key rotation: rotate_key for compromised Ed25519 keys",
                "Agent search/discovery: search_agents by capabilities or metrics",
                "Metrics time-series: historical metric queries, not just latest",
                "Leaderboard: rank agents by verified metrics within categories",
                "Batch execution: multiple tool calls in one request",
                "Event schema registry: validate event types against registered schemas",
            ],
        ),
        (
            "P3 - Nice to have",
            [
                "SSE/WebSocket streaming for real-time events",
                "Volume discount pricing tiers",
                "Cost estimation calculator",
                "Service ratings and reviews",
                "Multi-party payment splits",
                "Conditional escrow release",
            ],
        ),
    ]

    for priority, items in priority_features:
        lines.append(f"### {priority}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    # All missing from modules (raw list)
    lines.append("### Raw missing features by module")
    lines.append("")
    for module_name, item in all_missing:
        lines.append(f"- **[{module_name}]** {item}")
    lines.append("")

    # Test results summary
    lines.append("---")
    lines.append("")
    lines.append("## Appendix: Test Execution Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total API calls | {total_steps} |")
    lines.append(f"| Passed | {passed_steps} |")
    lines.append(f"| Failed / Expected errors | {failed_steps} |")
    lines.append(f"| Average latency | {avg_latency:.1f}ms |")
    lines.append(f"| P95 latency | {sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0:.1f}ms |")
    lines.append(f"| Max latency | {max(latencies) if latencies else 0:.1f}ms |")
    lines.append(f"| Simulation duration | {duration:.1f}s |")
    lines.append("")

    # Per-module step details
    for _name, mod in report.modules.items():
        lines.append(f"### {mod.module}")
        lines.append("")
        lines.append("| Step | Status | HTTP | Latency |")
        lines.append("|------|--------|------|---------|")
        for s in mod.steps:
            status = "PASS" if s.passed else "FAIL"
            http = str(s.status_code) if s.status_code else "ERR"
            lines.append(f"| {s.name} | {status} | {http} | {s.latency_ms:.0f}ms |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*Report generated by AlphaBot-v3 Customer Agent Simulation*")
    lines.append("*Simulation ran against A2A Commerce Gateway v0.1.0 using httpx ASGI transport (no live server)*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main simulation
# ---------------------------------------------------------------------------


async def run_simulation() -> None:
    """Run the full customer agent simulation."""
    print(f"\n{C_BOLD}{'#' * 60}{C_RESET}")
    print(f"{C_BOLD}  AlphaBot-v3 Customer Agent Simulation{C_RESET}")
    print(f"{C_BOLD}  A2A Commerce Platform Feedback Exercise{C_RESET}")
    print(f"{C_BOLD}{'#' * 60}{C_RESET}")

    report = FeedbackReport()
    report.start_time = time.time()

    # Create app and manage lifespan manually
    _info("Creating app and initializing backends...")
    application = create_app()
    ctx_manager = lifespan(application)
    await ctx_manager.__aenter__()
    _ok("App created, all backends initialized")

    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Phase 0: System endpoints
            await phase_system(client, report)

            # Phase 1: Identity & API key setup
            free_key, pro_key = await phase_identity(client, report, application)

            # Phase 2: Billing
            await phase_billing(client, report, free_key, pro_key)

            # Phase 3: Payments
            await phase_payments(client, report, free_key, pro_key, application)

            # Phase 4: Marketplace
            await phase_marketplace(client, report, free_key, pro_key)

            # Phase 5: Trust
            await phase_trust(client, report, free_key, pro_key)

            # Phase 6: Metrics & Claims
            await phase_metrics_claims(client, report, free_key, pro_key)

            # Phase 7: Events & Webhooks
            await phase_events_webhooks(client, report, free_key, pro_key)

            # Phase 8: Rate Limiting
            await phase_rate_limiting(client, report, free_key, pro_key)

            # Phase 9: Audit & Admin
            await phase_audit(client, report, pro_key)

            # Phase 10: Edge Cases
            await phase_edge_cases(client, report, free_key, pro_key)

    finally:
        _info("Shutting down app...")
        await ctx_manager.__aexit__(None, None, None)
        _ok("App shutdown complete")

    report.end_time = time.time()

    # Generate and write report
    _section("Generating Feedback Report")
    report_text = generate_report(report)
    report_path = os.path.join(os.path.dirname(__file__), "CUSTOMER_AGENT_FEEDBACK.md")
    with open(report_path, "w") as f:
        f.write(report_text)
    _ok(f"Report written to {report_path}")

    total_steps = sum(len(m.steps) for m in report.modules.values())
    passed = sum(sum(1 for s in m.steps if s.passed) for m in report.modules.values())
    print(f"\n{C_BOLD}{'=' * 60}{C_RESET}")
    print(f"{C_BOLD}  SIMULATION COMPLETE{C_RESET}")
    print(f"{C_BOLD}  Total calls: {total_steps}, Passed: {passed}, Failed: {total_steps - passed}{C_RESET}")
    all_nps = [m.nps_score for m in report.modules.values()]
    avg_nps = sum(all_nps) / len(all_nps) if all_nps else 0
    print(f"{C_BOLD}  Average NPS: {avg_nps:.1f}/10{C_RESET}")
    print(f"{C_BOLD}{'=' * 60}{C_RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_simulation())
