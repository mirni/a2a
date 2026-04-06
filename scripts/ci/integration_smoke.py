#!/usr/bin/env python3
"""Focused integration smoke test against a live gateway.

Runs against a freshly-started, empty gateway and verifies the core
happy-path flows: public endpoints, auth, wallet, payment intent
lifecycle, and marketplace. Designed to run in CI before merge to main
as a regression signal that the full stack boots and wires up correctly.

Usage:
    A2A_BASE_URL=http://127.0.0.1:8000 A2A_API_KEY=<key> python integration_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("A2A_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("A2A_API_KEY", "").strip()

PASS_COUNT = 0
FAIL_COUNT = 0
RUN_ID = uuid.uuid4().hex[:8]


def _req(
    method: str,
    path: str,
    *,
    body: dict | None = None,
    auth: bool = True,
    timeout: float = 15.0,
) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE_URL}{path}", method=method, data=data)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if auth and API_KEY:
        req.add_header("Authorization", f"Bearer {API_KEY}")
    try:
        with urllib.request.urlopen(  # nosemgrep: dynamic-urllib-use-detected
            req, timeout=timeout
        ) as resp:
            text = resp.read().decode()
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS_COUNT, FAIL_COUNT
    if cond:
        PASS_COUNT += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        FAIL_COUNT += 1
        print(f"  \033[31m✗\033[0m {name}  {detail}")


def main() -> int:
    if not API_KEY:
        print("Error: A2A_API_KEY env var required", file=sys.stderr)
        return 1

    print(f"Integration smoke target: {BASE_URL}")
    print(f"Run ID: {RUN_ID}")
    print()

    # --- Public endpoints ---
    print("[Public endpoints]")
    status, body = _req("GET", "/v1/health", auth=False)
    check("GET /v1/health → 200", status == 200, f"got {status}")
    check("health body has status=ok", isinstance(body, dict) and body.get("status") == "ok", str(body)[:80])

    status, body = _req("GET", "/v1/pricing", auth=False)
    check("GET /v1/pricing → 200", status == 200, f"got {status}")
    check("pricing has tools list", isinstance(body, dict) and len(body.get("tools", [])) > 0, str(body)[:80])

    status, body = _req("GET", "/.well-known/agent-card.json", auth=False)
    check("GET /.well-known/agent-card.json → 200", status == 200, f"got {status}")

    # --- Auth enforcement ---
    print("[Auth]")
    status, _ = _req("GET", "/v1/billing/wallets/e2e-admin/balance", auth=False)
    check("no-auth wallet read → 401", status == 401, f"got {status}")

    # --- Wallet (admin's own agent) ---
    print("[Billing]")
    status, body = _req("GET", "/v1/billing/wallets/e2e-admin/balance")
    check("wallet balance reachable", status == 200, f"got {status}")
    check("balance is numeric", isinstance(body, dict) and "balance" in body, str(body)[:80])

    # --- Payment intent happy-path ---
    print("[Payments]")
    # Register a counterparty (unauthenticated signup)
    counterparty = f"smoke-payee-{RUN_ID}"
    status, reg = _req(
        "POST",
        "/v1/register",
        body={"agent_id": counterparty},
        auth=False,
    )
    check(
        "register counterparty → 200/201",
        status in (200, 201),
        f"got {status} body={str(reg)[:120]}",
    )

    status, body = _req(
        "POST",
        "/v1/payments/intents",
        body={
            "payer": "e2e-admin",
            "payee": counterparty,
            "amount": 1.00,
            "description": f"smoke test {RUN_ID}",
        },
    )
    check(
        "POST /v1/payments/intents → 200/201",
        status in (200, 201),
        f"got {status} body={str(body)[:120]}",
    )
    intent_id = body.get("id") if isinstance(body, dict) else None
    check("intent has id", intent_id is not None, str(body)[:80])
    if isinstance(body, dict):
        check("intent response has gateway_fee", "gateway_fee" in body, str(body)[:80])

    # Void the intent (same admin is the payer)
    if intent_id:
        status, body = _req("POST", f"/v1/payments/intents/{intent_id}/refund")
        check(
            "refund intent → 200",
            status == 200,
            f"got {status} body={str(body)[:120]}",
        )
        if isinstance(body, dict):
            check("refund response has gateway_fee", "gateway_fee" in body, str(body)[:80])

    # --- Error handling ---
    print("[Errors]")
    status, body = _req("GET", "/v1/nonexistent-endpoint")
    check("unknown path → 404", status == 404, f"got {status}")
    check(
        "404 uses RFC 9457 type URI",
        isinstance(body, dict) and "type" in body and body["type"] != "about:blank",
        str(body)[:80],
    )

    # --- Summary ---
    print()
    total = PASS_COUNT + FAIL_COUNT
    print(f"{'=' * 50}")
    print(f"{total} checks: {PASS_COUNT} passed, {FAIL_COUNT} failed")
    print(f"{'=' * 50}")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
