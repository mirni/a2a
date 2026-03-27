#!/usr/bin/env python3
"""End-to-end tests for the A2A Commerce Platform.

Target: https://api.greenhelix.net
Run:    A2A_API_KEY=<pro-key> python e2e_tests.py
Flags:  --dry-run    Print test plan without executing
        --timeout N  Per-request timeout in seconds (default: 15)
        --verbose    Print response bodies on failure

Requires: httpx (pip install httpx)
Exit codes: 0 = all passed, 1 = any failed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine


# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

class _C:
    """ANSI color codes. Disabled when stdout is not a TTY."""
    _enabled = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    GREEN = "\033[32m" if _enabled else ""
    RED = "\033[31m" if _enabled else ""
    YELLOW = "\033[33m" if _enabled else ""
    CYAN = "\033[36m" if _enabled else ""
    BOLD = "\033[1m" if _enabled else ""
    DIM = "\033[2m" if _enabled else ""
    RESET = "\033[0m" if _enabled else ""


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

class Status(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class TestResult:
    name: str
    status: Status
    duration_ms: float = 0.0
    detail: str = ""


@dataclass
class TestSuite:
    results: list[TestResult] = field(default_factory=list)

    def record(self, result: TestResult) -> None:
        icon = {
            Status.PASS: f"{_C.GREEN}\u2713{_C.RESET}",
            Status.FAIL: f"{_C.RED}\u2717{_C.RESET}",
            Status.SKIP: f"{_C.YELLOW}~{_C.RESET}",
        }[result.status]
        timing = f"{_C.DIM}({result.duration_ms:.0f}ms){_C.RESET}"
        detail_str = f"  {_C.DIM}{result.detail}{_C.RESET}" if result.detail else ""
        print(f"  {icon} {result.name} {timing}{detail_str}")
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == Status.SKIP)

    def summary(self) -> str:
        total = len(self.results)
        parts = []
        if self.passed:
            parts.append(f"{_C.GREEN}{self.passed} passed{_C.RESET}")
        if self.failed:
            parts.append(f"{_C.RED}{self.failed} failed{_C.RESET}")
        if self.skipped:
            parts.append(f"{_C.YELLOW}{self.skipped} skipped{_C.RESET}")
        return f"{total} tests: {', '.join(parts)}"

    @property
    def ok(self) -> bool:
        return self.failed == 0


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://api.greenhelix.net"
RUN_ID = f"e2e-test-{int(time.time())}-{uuid.uuid4().hex[:8]}"
AGENT_ID = f"e2e-agent-{RUN_ID}"
PAYEE_AGENT = f"e2e-payee-{RUN_ID}"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_http: "httpx.AsyncClient | None" = None
_timeout: float = 15.0
_verbose: bool = False


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


async def _get(
    path: str,
    *,
    headers: dict[str, str] | None = None,
    allow_redirects: bool = True,
) -> "httpx.Response":
    assert _http is not None
    return await _http.get(
        path,
        headers=headers or {},
        follow_redirects=allow_redirects,
    )


async def _post(
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> "httpx.Response":
    assert _http is not None
    return await _http.post(
        path,
        json=json_body,
        headers=headers or {},
    )


async def _execute(
    tool: str,
    params: dict[str, Any],
    api_key: str,
) -> "httpx.Response":
    """POST /v1/execute with the given tool and params."""
    return await _post(
        "/v1/execute",
        json_body={"tool": tool, "params": params},
        headers=_auth_headers(api_key),
    )


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def _run_test(
    suite: TestSuite,
    name: str,
    fn: Callable[[], Coroutine[Any, Any, None]],
) -> None:
    """Run a single async test function, capturing result into the suite."""
    t0 = time.monotonic()
    try:
        await fn()
        elapsed = (time.monotonic() - t0) * 1000
        suite.record(TestResult(name, Status.PASS, elapsed))
    except _Skip as e:
        elapsed = (time.monotonic() - t0) * 1000
        suite.record(TestResult(name, Status.SKIP, elapsed, str(e)))
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        detail = str(e)
        if _verbose:
            detail = traceback.format_exc()
        suite.record(TestResult(name, Status.FAIL, elapsed, detail))


class _Skip(Exception):
    """Raised to skip a test with a message."""
    pass


def _assert(condition: bool, msg: str = "assertion failed") -> None:
    if not condition:
        raise AssertionError(msg)


def _assert_status(resp: "httpx.Response", expected: int) -> None:
    if resp.status_code != expected:
        body_preview = resp.text[:300] if resp.text else "(empty)"
        raise AssertionError(
            f"Expected HTTP {expected}, got {resp.status_code}. Body: {body_preview}"
        )


def _assert_json_key(data: dict, key: str, msg: str = "") -> Any:
    if key not in data:
        raise AssertionError(msg or f"Missing key '{key}' in response: {json.dumps(data)[:200]}")
    return data[key]


# ---------------------------------------------------------------------------
# Cleanup registry
# ---------------------------------------------------------------------------

_cleanup_tasks: list[Callable[[], Coroutine[Any, Any, None]]] = []


def _register_cleanup(fn: Callable[[], Coroutine[Any, Any, None]]) -> None:
    _cleanup_tasks.append(fn)


async def _run_cleanup(api_key: str) -> None:
    for fn in reversed(_cleanup_tasks):
        try:
            await fn()
        except Exception as e:
            print(f"  {_C.DIM}cleanup warning: {e}{_C.RESET}")


# ---------------------------------------------------------------------------
# Infrastructure Tests
# ---------------------------------------------------------------------------

async def test_health(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/health")
        _assert_status(resp, 200)
        data = resp.json()
        _assert_json_key(data, "status")
        _assert(data["status"] == "ok", f"Expected status=ok, got {data['status']}")

    await _run_test(suite, "GET /v1/health returns 200 with status=ok", _test)


async def test_health_version(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/health")
        _assert_status(resp, 200)
        data = resp.json()
        _assert_json_key(data, "version")
        _assert(isinstance(data["version"], str), "version should be a string")

    await _run_test(suite, "GET /v1/health includes version field", _test)


async def test_health_tools_count(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/health")
        _assert_status(resp, 200)
        data = resp.json()
        _assert_json_key(data, "tools")
        _assert(isinstance(data["tools"], int) and data["tools"] > 0,
                f"Expected tools > 0, got {data.get('tools')}")

    await _run_test(suite, "GET /v1/health reports tool count > 0", _test)


async def test_pricing_list(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/pricing")
        _assert_status(resp, 200)
        data = resp.json()
        tools = _assert_json_key(data, "tools")
        _assert(isinstance(tools, list) and len(tools) > 0,
                "Expected non-empty tools array")
        # Verify each tool has required fields
        for t in tools:
            _assert_json_key(t, "name")
            _assert_json_key(t, "pricing")

    await _run_test(suite, "GET /v1/pricing returns tool catalog", _test)


async def test_pricing_single_tool(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/pricing/get_balance")
        _assert_status(resp, 200)
        data = resp.json()
        tool = _assert_json_key(data, "tool")
        _assert(tool["name"] == "get_balance",
                f"Expected tool name get_balance, got {tool.get('name')}")
        _assert_json_key(tool, "pricing")
        _assert_json_key(tool, "tier_required")

    await _run_test(suite, "GET /v1/pricing/get_balance returns specific tool", _test)


async def test_pricing_unknown_tool(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/pricing/nonexistent_tool_xyz")
        _assert_status(resp, 404)

    await _run_test(suite, "GET /v1/pricing/<unknown> returns 404", _test)


async def test_openapi_spec(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/openapi.json")
        _assert_status(resp, 200)
        data = resp.json()
        _assert_json_key(data, "openapi")
        _assert(data["openapi"].startswith("3.1"),
                f"Expected OpenAPI 3.1.x, got {data['openapi']}")
        _assert_json_key(data, "info")
        _assert_json_key(data, "paths")
        _assert_json_key(data, "components")

    await _run_test(suite, "GET /v1/openapi.json returns valid OpenAPI 3.1 spec", _test)


async def test_metrics(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/metrics")
        _assert_status(resp, 200)
        content_type = resp.headers.get("content-type", "")
        _assert("text/plain" in content_type,
                f"Expected text/plain content-type, got {content_type}")
        body = resp.text
        _assert("a2a_requests_total" in body,
                "Expected Prometheus metric 'a2a_requests_total' in body")
        _assert("a2a_errors_total" in body,
                "Expected Prometheus metric 'a2a_errors_total' in body")

    await _run_test(suite, "GET /v1/metrics returns Prometheus-format metrics", _test)


async def test_signing_key(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/signing-key")
        _assert_status(resp, 200)
        data = resp.json()
        _assert_json_key(data, "public_key")
        _assert_json_key(data, "algorithm")
        algo = data["algorithm"]
        _assert(algo in ("crystals-dilithium", "hmac-sha3-256"),
                f"Unexpected algorithm: {algo}")

    await _run_test(suite, "GET /v1/signing-key returns key info", _test)


async def test_correlation_id(suite: TestSuite) -> None:
    async def _test() -> None:
        custom_id = f"e2e-corr-{uuid.uuid4().hex[:12]}"
        resp = await _get("/v1/health", headers={"X-Request-ID": custom_id})
        _assert_status(resp, 200)
        echoed = resp.headers.get("x-request-id", "")
        _assert(echoed == custom_id,
                f"Expected X-Request-ID={custom_id}, got '{echoed}'")

    await _run_test(suite, "X-Request-ID correlation header echoed back", _test)


async def test_correlation_id_generated(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _get("/v1/health")
        _assert_status(resp, 200)
        generated = resp.headers.get("x-request-id", "")
        _assert(len(generated) > 0,
                "Expected auto-generated X-Request-ID when none sent")

    await _run_test(suite, "X-Request-ID auto-generated when not provided", _test)


async def test_backward_compat_health(suite: TestSuite) -> None:
    async def _test() -> None:
        assert _http is not None
        # Don't follow redirects to inspect the 301
        resp = await _http.get("/health", follow_redirects=False)
        _assert(resp.status_code == 301,
                f"Expected 301 redirect, got {resp.status_code}")
        location = resp.headers.get("location", "")
        _assert("/v1/health" in location,
                f"Expected redirect to /v1/health, got location={location}")

    await _run_test(suite, "GET /health redirects to /v1/health (301)", _test)


async def test_backward_compat_pricing(suite: TestSuite) -> None:
    async def _test() -> None:
        assert _http is not None
        resp = await _http.get("/pricing", follow_redirects=False)
        _assert(resp.status_code == 301,
                f"Expected 301 redirect, got {resp.status_code}")
        location = resp.headers.get("location", "")
        _assert("/v1/pricing" in location,
                f"Expected redirect to /v1/pricing, got location={location}")

    await _run_test(suite, "GET /pricing redirects to /v1/pricing (301)", _test)


async def test_backward_compat_execute(suite: TestSuite) -> None:
    async def _test() -> None:
        assert _http is not None
        resp = await _http.post("/execute", json={}, follow_redirects=False)
        _assert(resp.status_code == 307,
                f"Expected 307 redirect, got {resp.status_code}")
        location = resp.headers.get("location", "")
        _assert("/v1/execute" in location,
                f"Expected redirect to /v1/execute, got location={location}")

    await _run_test(suite, "POST /execute redirects to /v1/execute (307)", _test)


# ---------------------------------------------------------------------------
# Authentication Tests
# ---------------------------------------------------------------------------

async def test_auth_missing(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _post(
            "/v1/execute",
            json_body={"tool": "get_balance", "params": {"agent_id": "test"}},
        )
        _assert_status(resp, 401)
        data = resp.json()
        _assert(data.get("success") is False, "Expected success=false")

    await _run_test(suite, "POST /v1/execute without auth returns 401", _test)


async def test_auth_invalid_key(suite: TestSuite) -> None:
    async def _test() -> None:
        resp = await _post(
            "/v1/execute",
            json_body={"tool": "get_balance", "params": {"agent_id": "test"}},
            headers={"Authorization": "Bearer invalid_key_that_does_not_exist"},
        )
        _assert_status(resp, 401)

    await _run_test(suite, "POST /v1/execute with invalid key returns 401", _test)


async def test_auth_valid_key(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute("get_balance", {"agent_id": AGENT_ID}, api_key)
        # 200 means auth passed (even if balance is 0 or wallet not found, auth was OK)
        # The tool might return 404 for wallet not found, but that is post-auth.
        # We accept 200 or 404 (wallet_not_found) as evidence that auth succeeded.
        _assert(resp.status_code in (200, 404),
                f"Expected 200 or 404 (post-auth), got {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            _assert(data.get("success") is True, "Expected success=true")

    await _run_test(suite, "POST /v1/execute with valid key authenticates", _test)


# ---------------------------------------------------------------------------
# Billing Tests
# ---------------------------------------------------------------------------

async def test_billing_get_balance(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute("get_balance", {"agent_id": AGENT_ID}, api_key)
        # Wallet may or may not exist yet; both 200 and 404 are acceptable
        _assert(resp.status_code in (200, 404),
                f"Expected 200 or 404, got {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            _assert(data.get("success") is True, "Expected success=true")
            _assert("balance" in data.get("result", {}),
                    "Expected 'balance' in result")

    await _run_test(suite, "get_balance returns balance or wallet_not_found", _test)


async def test_billing_deposit(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "deposit",
            {"agent_id": AGENT_ID, "amount": 100.0, "description": "e2e test deposit"},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        new_balance = data.get("result", {}).get("new_balance")
        _assert(new_balance is not None, "Expected new_balance in result")
        _assert(isinstance(new_balance, (int, float)) and new_balance >= 100.0,
                f"Expected new_balance >= 100, got {new_balance}")

    await _run_test(suite, "deposit credits into test agent wallet", _test)


async def test_billing_balance_after_deposit(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute("get_balance", {"agent_id": AGENT_ID}, api_key)
        _assert_status(resp, 200)
        data = resp.json()
        balance = data.get("result", {}).get("balance", 0)
        _assert(balance >= 100.0,
                f"Expected balance >= 100 after deposit, got {balance}")

    await _run_test(suite, "get_balance reflects deposited credits", _test)


async def test_billing_usage_summary(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute("get_usage_summary", {"agent_id": AGENT_ID}, api_key)
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data.get("result", {})
        # Usage summary should have cost/calls/tokens fields
        _assert("total_cost" in result or "total_calls" in result,
                f"Expected usage fields in result: {result}")

    await _run_test(suite, "get_usage_summary returns usage data", _test)


# ---------------------------------------------------------------------------
# Payments Tests
# ---------------------------------------------------------------------------

_created_intent_id: str | None = None
_created_escrow_id: str | None = None


async def test_payments_create_intent(suite: TestSuite, api_key: str) -> None:
    global _created_intent_id

    async def _test() -> None:
        global _created_intent_id
        # First ensure payee has a wallet too
        await _execute(
            "deposit",
            {"agent_id": PAYEE_AGENT, "amount": 10.0, "description": "e2e payee setup"},
            api_key,
        )
        resp = await _execute(
            "create_intent",
            {
                "payer": AGENT_ID,
                "payee": PAYEE_AGENT,
                "amount": 5.0,
                "description": "e2e test payment",
                "idempotency_key": f"e2e-intent-{RUN_ID}",
            },
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert_json_key(result, "id")
        _assert_json_key(result, "status")
        _created_intent_id = result["id"]

    await _run_test(suite, "create_intent creates a payment intent", _test)


async def test_payments_capture_intent(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        if _created_intent_id is None:
            raise _Skip("No intent created in previous test")
        resp = await _execute(
            "capture_intent",
            {"intent_id": _created_intent_id},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert_json_key(result, "status")

    await _run_test(suite, "capture_intent settles the payment", _test)


async def test_payments_create_escrow(suite: TestSuite, api_key: str) -> None:
    global _created_escrow_id

    async def _test() -> None:
        global _created_escrow_id
        resp = await _execute(
            "create_escrow",
            {
                "payer": AGENT_ID,
                "payee": PAYEE_AGENT,
                "amount": 5.0,
                "description": "e2e test escrow",
                "timeout_hours": 1,
            },
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert_json_key(result, "id")
        _assert_json_key(result, "status")
        _created_escrow_id = result["id"]

    await _run_test(suite, "create_escrow holds funds in escrow", _test)


async def test_payments_release_escrow(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        if _created_escrow_id is None:
            raise _Skip("No escrow created in previous test")
        resp = await _execute(
            "release_escrow",
            {"escrow_id": _created_escrow_id},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")

    await _run_test(suite, "release_escrow releases funds to payee", _test)


async def test_payments_history(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "get_payment_history",
            {"agent_id": AGENT_ID, "limit": 10},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")

    await _run_test(suite, "get_payment_history returns history", _test)


# ---------------------------------------------------------------------------
# Marketplace Tests
# ---------------------------------------------------------------------------

_registered_service_id: str | None = None


async def test_marketplace_register(suite: TestSuite, api_key: str) -> None:
    global _registered_service_id

    async def _test() -> None:
        global _registered_service_id
        service_name = f"E2E Test Service {RUN_ID}"
        resp = await _execute(
            "register_service",
            {
                "provider_id": AGENT_ID,
                "name": service_name,
                "description": "Automated e2e test service — safe to delete",
                "category": "testing",
                "tools": ["test_tool"],
                "tags": ["e2e", "automated"],
                "endpoint": "https://example.com/e2e-test",
                "pricing": {"model": "per_call", "cost": 0.01},
            },
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert_json_key(result, "id")
        _registered_service_id = result["id"]

    await _run_test(suite, "register_service registers in marketplace (pro tier)", _test)


async def test_marketplace_search(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "search_services",
            {"query": "e2e test", "limit": 10},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")

    await _run_test(suite, "search_services returns results", _test)


async def test_marketplace_best_match(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "best_match",
            {"query": "testing service", "prefer": "cost", "limit": 5},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")

    await _run_test(suite, "best_match finds ranked matches", _test)


# ---------------------------------------------------------------------------
# Trust Tests
# ---------------------------------------------------------------------------

async def test_trust_score(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "get_trust_score",
            {"server_id": "e2e-test-server", "window": "24h"},
            api_key,
        )
        # Server may not exist, 200 (with default score) or 404 both acceptable
        _assert(resp.status_code in (200, 404),
                f"Expected 200 or 404, got {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            _assert(data.get("success") is True, "Expected success=true")
            result = data["result"]
            _assert_json_key(result, "composite_score")

    await _run_test(suite, "get_trust_score returns score or not_found", _test)


async def test_trust_search_servers(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "search_servers",
            {"limit": 5},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")

    await _run_test(suite, "search_servers returns server list", _test)


# ---------------------------------------------------------------------------
# Webhook Tests
# ---------------------------------------------------------------------------

_registered_webhook_id: str | None = None


async def test_webhook_register(suite: TestSuite, api_key: str) -> None:
    global _registered_webhook_id

    async def _test() -> None:
        global _registered_webhook_id
        resp = await _execute(
            "register_webhook",
            {
                "agent_id": AGENT_ID,
                "url": "https://example.com/e2e-webhook-sink",
                "event_types": ["billing.deposit", "payments.captured"],
                "secret": f"e2e-secret-{RUN_ID}",
            },
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert_json_key(result, "id")
        _registered_webhook_id = result["id"]

        # Register cleanup to delete this webhook
        async def _cleanup_webhook() -> None:
            if _registered_webhook_id:
                await _execute(
                    "delete_webhook",
                    {"webhook_id": _registered_webhook_id},
                    api_key,
                )
        _register_cleanup(_cleanup_webhook)

    await _run_test(suite, "register_webhook creates webhook subscription", _test)


async def test_webhook_list(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "list_webhooks",
            {"agent_id": AGENT_ID},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert_json_key(result, "webhooks")
        webhooks = result["webhooks"]
        _assert(isinstance(webhooks, list), "Expected webhooks to be a list")
        if _registered_webhook_id:
            found = any(w.get("id") == _registered_webhook_id for w in webhooks)
            _assert(found, f"Registered webhook {_registered_webhook_id} not found in list")

    await _run_test(suite, "list_webhooks includes registered webhook", _test)


async def test_webhook_delete(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        if _registered_webhook_id is None:
            raise _Skip("No webhook registered in previous test")
        resp = await _execute(
            "delete_webhook",
            {"webhook_id": _registered_webhook_id},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        result = data["result"]
        _assert(result.get("deleted") is True, "Expected deleted=true")

    await _run_test(suite, "delete_webhook removes webhook", _test)


# ---------------------------------------------------------------------------
# Event Bus Tests
# ---------------------------------------------------------------------------

async def test_event_publish(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "publish_event",
            {
                "event_type": "e2e.test_event",
                "source": "e2e_tests",
                "payload": {"run_id": RUN_ID, "timestamp": time.time()},
            },
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        _assert_json_key(data["result"], "event_id")

    await _run_test(suite, "publish_event publishes to event bus", _test)


async def test_event_query(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "get_events",
            {"event_type": "e2e.test_event", "limit": 10},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        _assert_json_key(data["result"], "events")

    await _run_test(suite, "get_events queries event bus", _test)


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------

async def test_rate_limit_headers(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute("get_balance", {"agent_id": AGENT_ID}, api_key)
        # Rate limit headers are optional; just check if they appear
        has_ratelimit = any(
            k.lower().startswith("x-ratelimit") for k in resp.headers.keys()
        )
        if not has_ratelimit:
            raise _Skip("No X-RateLimit headers present (optional)")
        # If present, validate format
        for key in ("x-ratelimit-limit", "x-ratelimit-remaining"):
            val = resp.headers.get(key)
            if val is not None:
                _assert(val.isdigit(), f"Expected numeric {key}, got '{val}'")

    await _run_test(suite, "Rate limit headers present in responses (if enabled)", _test)


# ---------------------------------------------------------------------------
# Response Signing Tests
# ---------------------------------------------------------------------------

async def test_response_signing(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute("get_balance", {"agent_id": AGENT_ID}, api_key)
        sig = resp.headers.get("x-a2a-signature-dilithium")
        if sig is None:
            raise _Skip("No X-A2A-Signature-Dilithium header (signing may be disabled)")
        _assert(len(sig) > 0, "Signature header is empty")

    await _run_test(suite, "Response includes X-A2A-Signature-Dilithium header", _test)


# ---------------------------------------------------------------------------
# Execute Error Handling Tests
# ---------------------------------------------------------------------------

async def test_execute_missing_tool(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _post(
            "/v1/execute",
            json_body={"params": {"agent_id": "test"}},
            headers=_auth_headers(api_key),
        )
        _assert_status(resp, 400)

    await _run_test(suite, "POST /v1/execute without 'tool' field returns 400", _test)


async def test_execute_unknown_tool(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "nonexistent_tool_xyz_12345",
            {},
            api_key,
        )
        _assert_status(resp, 400)

    await _run_test(suite, "POST /v1/execute with unknown tool returns 400", _test)


async def test_execute_invalid_json(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        assert _http is not None
        resp = await _http.post(
            "/v1/execute",
            content=b"this is not json",
            headers={
                **_auth_headers(api_key),
                "Content-Type": "application/json",
            },
        )
        _assert_status(resp, 400)

    await _run_test(suite, "POST /v1/execute with invalid JSON returns 400", _test)


# ---------------------------------------------------------------------------
# Free Tier Tests (optional, if A2A_FREE_KEY provided)
# ---------------------------------------------------------------------------

async def test_free_tier_denied_pro_tool(suite: TestSuite, free_key: str) -> None:
    async def _test() -> None:
        # create_escrow requires pro tier
        resp = await _execute(
            "create_escrow",
            {"payer": "test", "payee": "test2", "amount": 1.0},
            free_key,
        )
        _assert_status(resp, 403)
        data = resp.json()
        error_code = data.get("error", {}).get("code", "")
        _assert(error_code == "insufficient_tier",
                f"Expected error code 'insufficient_tier', got '{error_code}'")

    await _run_test(suite, "Free tier denied access to pro-tier tool (create_escrow)", _test)


async def test_free_tier_allowed_free_tool(suite: TestSuite, free_key: str) -> None:
    async def _test() -> None:
        # get_balance is free-tier accessible
        resp = await _execute("get_balance", {"agent_id": "test"}, free_key)
        _assert(resp.status_code in (200, 404),
                f"Expected 200 or 404, got {resp.status_code}")

    await _run_test(suite, "Free tier can access free-tier tool (get_balance)", _test)


# ---------------------------------------------------------------------------
# SDK Tests (optional, if SDK is importable)
# ---------------------------------------------------------------------------

async def test_sdk_health(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        try:
            from a2a_client import A2AClient
        except ImportError:
            raise _Skip("a2a_client SDK not importable")

        async with A2AClient(BASE_URL, api_key=api_key, timeout=_timeout) as client:
            health = await client.health()
            _assert(health.status == "ok", f"Expected status=ok, got {health.status}")

    await _run_test(suite, "SDK: A2AClient.health() returns ok", _test)


async def test_sdk_pricing(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        try:
            from a2a_client import A2AClient
        except ImportError:
            raise _Skip("a2a_client SDK not importable")

        async with A2AClient(BASE_URL, api_key=api_key, timeout=_timeout) as client:
            tools = await client.pricing()
            _assert(len(tools) > 0, "Expected non-empty pricing list")

    await _run_test(suite, "SDK: A2AClient.pricing() returns tools", _test)


async def test_sdk_get_balance(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        try:
            from a2a_client import A2AClient
        except ImportError:
            raise _Skip("a2a_client SDK not importable")

        async with A2AClient(BASE_URL, api_key=api_key, timeout=_timeout) as client:
            try:
                balance = await client.get_balance(AGENT_ID)
                _assert(isinstance(balance, (int, float)),
                        f"Expected numeric balance, got {type(balance)}")
            except Exception as e:
                # WalletNotFoundError is acceptable if wallet setup hasn't run
                if "not_found" in str(e).lower() or "404" in str(e):
                    pass  # Acceptable
                else:
                    raise

    await _run_test(suite, "SDK: A2AClient.get_balance() works", _test)


async def test_sdk_execute(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        try:
            from a2a_client import A2AClient
        except ImportError:
            raise _Skip("a2a_client SDK not importable")

        async with A2AClient(BASE_URL, api_key=api_key, timeout=_timeout) as client:
            result = await client.execute("search_services", {"limit": 1})
            _assert(result.success is True or hasattr(result, "result"),
                    "Expected valid ExecuteResponse")

    await _run_test(suite, "SDK: A2AClient.execute() raw call works", _test)


# ---------------------------------------------------------------------------
# Audit Log Test
# ---------------------------------------------------------------------------

async def test_audit_log(suite: TestSuite, api_key: str) -> None:
    async def _test() -> None:
        resp = await _execute(
            "get_global_audit_log",
            {"limit": 5},
            api_key,
        )
        _assert_status(resp, 200)
        data = resp.json()
        _assert(data.get("success") is True, "Expected success=true")
        _assert_json_key(data["result"], "entries")

    await _run_test(suite, "get_global_audit_log returns entries (pro tier)", _test)


# ---------------------------------------------------------------------------
# Dry run plan
# ---------------------------------------------------------------------------

ALL_TESTS = [
    # Infrastructure
    ("Infrastructure", "GET /v1/health returns 200 with status=ok"),
    ("Infrastructure", "GET /v1/health includes version field"),
    ("Infrastructure", "GET /v1/health reports tool count > 0"),
    ("Infrastructure", "GET /v1/pricing returns tool catalog"),
    ("Infrastructure", "GET /v1/pricing/get_balance returns specific tool"),
    ("Infrastructure", "GET /v1/pricing/<unknown> returns 404"),
    ("Infrastructure", "GET /v1/openapi.json returns valid OpenAPI 3.1 spec"),
    ("Infrastructure", "GET /v1/metrics returns Prometheus-format metrics"),
    ("Infrastructure", "GET /v1/signing-key returns key info"),
    ("Infrastructure", "X-Request-ID correlation header echoed back"),
    ("Infrastructure", "X-Request-ID auto-generated when not provided"),
    ("Infrastructure", "GET /health redirects to /v1/health (301)"),
    ("Infrastructure", "GET /pricing redirects to /v1/pricing (301)"),
    ("Infrastructure", "POST /execute redirects to /v1/execute (307)"),
    # Authentication
    ("Authentication", "POST /v1/execute without auth returns 401"),
    ("Authentication", "POST /v1/execute with invalid key returns 401"),
    ("Authentication", "POST /v1/execute with valid key authenticates"),
    # Billing
    ("Billing", "get_balance returns balance or wallet_not_found"),
    ("Billing", "deposit credits into test agent wallet"),
    ("Billing", "get_balance reflects deposited credits"),
    ("Billing", "get_usage_summary returns usage data"),
    # Payments
    ("Payments", "create_intent creates a payment intent"),
    ("Payments", "capture_intent settles the payment"),
    ("Payments", "create_escrow holds funds in escrow"),
    ("Payments", "release_escrow releases funds to payee"),
    ("Payments", "get_payment_history returns history"),
    # Marketplace
    ("Marketplace", "register_service registers in marketplace (pro tier)"),
    ("Marketplace", "search_services returns results"),
    ("Marketplace", "best_match finds ranked matches"),
    # Trust
    ("Trust", "get_trust_score returns score or not_found"),
    ("Trust", "search_servers returns server list"),
    # Webhooks
    ("Webhooks", "register_webhook creates webhook subscription"),
    ("Webhooks", "list_webhooks includes registered webhook"),
    ("Webhooks", "delete_webhook removes webhook"),
    # Events
    ("Events", "publish_event publishes to event bus"),
    ("Events", "get_events queries event bus"),
    # Rate Limiting
    ("Rate Limiting", "Rate limit headers present in responses (if enabled)"),
    # Signing
    ("Signing", "Response includes X-A2A-Signature-Dilithium header"),
    # Error Handling
    ("Error Handling", "POST /v1/execute without 'tool' field returns 400"),
    ("Error Handling", "POST /v1/execute with unknown tool returns 400"),
    ("Error Handling", "POST /v1/execute with invalid JSON returns 400"),
    # Free Tier (optional)
    ("Free Tier", "Free tier denied access to pro-tier tool (create_escrow)"),
    ("Free Tier", "Free tier can access free-tier tool (get_balance)"),
    # Audit
    ("Audit", "get_global_audit_log returns entries (pro tier)"),
    # SDK (optional)
    ("SDK", "SDK: A2AClient.health() returns ok"),
    ("SDK", "SDK: A2AClient.pricing() returns tools"),
    ("SDK", "SDK: A2AClient.get_balance() works"),
    ("SDK", "SDK: A2AClient.execute() raw call works"),
]


def print_dry_run() -> None:
    print(f"\n{_C.BOLD}A2A Commerce Platform — E2E Test Plan (dry run){_C.RESET}")
    print(f"Target: {BASE_URL}")
    print(f"Run ID: {RUN_ID}\n")

    current_section = ""
    for section, name in ALL_TESTS:
        if section != current_section:
            current_section = section
            print(f"\n{_C.CYAN}{_C.BOLD}[{section}]{_C.RESET}")
        print(f"  - {name}")

    print(f"\n{_C.DIM}Total: {len(ALL_TESTS)} tests{_C.RESET}")
    print(f"{_C.DIM}Set A2A_API_KEY to run. Optional: A2A_FREE_KEY for tier tests.{_C.RESET}\n")


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_all(api_key: str, free_key: str | None) -> bool:
    """Run all e2e tests. Returns True if all passed."""
    global _http

    import httpx

    suite = TestSuite()

    print(f"\n{_C.BOLD}A2A Commerce Platform — End-to-End Tests{_C.RESET}")
    print(f"Target:   {BASE_URL}")
    print(f"Run ID:   {RUN_ID}")
    print(f"Agent:    {AGENT_ID}")
    print(f"Timeout:  {_timeout}s per request")
    print(f"Pro key:  {api_key[:12]}...{api_key[-4:]}" if len(api_key) > 16 else f"Pro key:  {api_key[:8]}...")
    if free_key:
        print(f"Free key: {free_key[:12]}...{free_key[-4:]}" if len(free_key) > 16 else f"Free key: {free_key[:8]}...")
    print()

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        timeout=httpx.Timeout(_timeout),
        follow_redirects=True,
    ) as client:
        _http = client

        # --- Infrastructure ---
        print(f"{_C.CYAN}{_C.BOLD}[Infrastructure]{_C.RESET}")
        await test_health(suite)
        await test_health_version(suite)
        await test_health_tools_count(suite)
        await test_pricing_list(suite)
        await test_pricing_single_tool(suite)
        await test_pricing_unknown_tool(suite)
        await test_openapi_spec(suite)
        await test_metrics(suite)
        await test_signing_key(suite)
        await test_correlation_id(suite)
        await test_correlation_id_generated(suite)
        await test_backward_compat_health(suite)
        await test_backward_compat_pricing(suite)
        await test_backward_compat_execute(suite)

        # --- Authentication ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Authentication]{_C.RESET}")
        await test_auth_missing(suite)
        await test_auth_invalid_key(suite)
        await test_auth_valid_key(suite, api_key)

        # --- Billing ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Billing]{_C.RESET}")
        await test_billing_get_balance(suite, api_key)
        await test_billing_deposit(suite, api_key)
        await test_billing_balance_after_deposit(suite, api_key)
        await test_billing_usage_summary(suite, api_key)

        # --- Payments ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Payments]{_C.RESET}")
        await test_payments_create_intent(suite, api_key)
        await test_payments_capture_intent(suite, api_key)
        await test_payments_create_escrow(suite, api_key)
        await test_payments_release_escrow(suite, api_key)
        await test_payments_history(suite, api_key)

        # --- Marketplace ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Marketplace]{_C.RESET}")
        await test_marketplace_register(suite, api_key)
        await test_marketplace_search(suite, api_key)
        await test_marketplace_best_match(suite, api_key)

        # --- Trust ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Trust]{_C.RESET}")
        await test_trust_score(suite, api_key)
        await test_trust_search_servers(suite, api_key)

        # --- Webhooks ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Webhooks]{_C.RESET}")
        await test_webhook_register(suite, api_key)
        await test_webhook_list(suite, api_key)
        await test_webhook_delete(suite, api_key)

        # --- Events ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Events]{_C.RESET}")
        await test_event_publish(suite, api_key)
        await test_event_query(suite, api_key)

        # --- Rate Limiting ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Rate Limiting]{_C.RESET}")
        await test_rate_limit_headers(suite, api_key)

        # --- Response Signing ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Response Signing]{_C.RESET}")
        await test_response_signing(suite, api_key)

        # --- Error Handling ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Error Handling]{_C.RESET}")
        await test_execute_missing_tool(suite, api_key)
        await test_execute_unknown_tool(suite, api_key)
        await test_execute_invalid_json(suite, api_key)

        # --- Free Tier (optional) ---
        if free_key:
            print(f"\n{_C.CYAN}{_C.BOLD}[Free Tier]{_C.RESET}")
            await test_free_tier_denied_pro_tool(suite, free_key)
            await test_free_tier_allowed_free_tool(suite, free_key)
        else:
            print(f"\n{_C.CYAN}{_C.BOLD}[Free Tier]{_C.RESET}")
            suite.record(TestResult(
                "Free tier tests",
                Status.SKIP, 0,
                "Set A2A_FREE_KEY env var to enable",
            ))

        # --- Audit ---
        print(f"\n{_C.CYAN}{_C.BOLD}[Audit]{_C.RESET}")
        await test_audit_log(suite, api_key)

        # --- SDK (optional) ---
        print(f"\n{_C.CYAN}{_C.BOLD}[SDK]{_C.RESET}")
        await test_sdk_health(suite, api_key)
        await test_sdk_pricing(suite, api_key)
        await test_sdk_get_balance(suite, api_key)
        await test_sdk_execute(suite, api_key)

        # --- Cleanup ---
        print(f"\n{_C.DIM}Running cleanup...{_C.RESET}")
        await _run_cleanup(api_key)

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"{_C.BOLD}{suite.summary()}{_C.RESET}")
    print(f"{'=' * 60}\n")

    return suite.ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A2A Commerce Platform — End-to-End Tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  A2A_API_KEY   Required. Pro-tier API key.\n"
            "  A2A_FREE_KEY  Optional. Free-tier API key for tier tests.\n"
            "  A2A_BASE_URL  Optional. Override base URL (default: https://api.greenhelix.net).\n"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print test plan without executing",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-request timeout in seconds (default: 15)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print full tracebacks on failure",
    )
    args = parser.parse_args()

    if args.dry_run:
        print_dry_run()
        sys.exit(0)

    # --- Configuration ---
    global BASE_URL, _timeout, _verbose
    _timeout = args.timeout
    _verbose = args.verbose

    base_url_override = os.environ.get("A2A_BASE_URL")
    if base_url_override:
        BASE_URL = base_url_override.rstrip("/")

    api_key = os.environ.get("A2A_API_KEY", "").strip()
    if not api_key:
        print(f"{_C.RED}Error: A2A_API_KEY environment variable is required.{_C.RESET}")
        print(f"Usage: A2A_API_KEY=<your-pro-key> python {sys.argv[0]}")
        sys.exit(1)

    free_key = os.environ.get("A2A_FREE_KEY", "").strip() or None

    # --- Validate httpx is available ---
    try:
        import httpx  # noqa: F401
    except ImportError:
        print(f"{_C.RED}Error: httpx is required. Install with: pip install httpx{_C.RESET}")
        sys.exit(1)

    # --- Run ---
    try:
        ok = asyncio.run(run_all(api_key, free_key))
    except KeyboardInterrupt:
        print(f"\n{_C.YELLOW}Interrupted.{_C.RESET}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{_C.RED}Fatal error: {e}{_C.RESET}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(1)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
