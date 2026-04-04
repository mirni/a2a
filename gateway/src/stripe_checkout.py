"""Stripe Checkout integration for fiat on-ramp.

Provides two routes:
- POST /v1/checkout — Create a Stripe Checkout session (credit purchase)
- POST /v1/stripe-webhook — Handle Stripe webhook events (session completed → deposit)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from gateway.src.auth import extract_api_key
from gateway.src.errors import error_response, handle_product_exception

logger = logging.getLogger("a2a.stripe_checkout")

router = APIRouter()

# Credit pricing: $1 = 100 credits (configurable via env)
CREDITS_PER_DOLLAR = int(os.environ.get("A2A_CREDITS_PER_DOLLAR", "100"))

# In-memory fallback for dedup (supplemented by DB persistence below)
_processed_sessions: set[str] = set()

# Maximum age (in seconds) of a webhook timestamp we will accept
_MAX_WEBHOOK_AGE_SECONDS = 300

# Preset credit packages
PACKAGES: dict[str, dict[str, int | str]] = {
    "starter": {"credits": 1_000, "price_cents": 1000, "label": "1,000 credits"},
    "growth": {"credits": 5_000, "price_cents": 4500, "label": "5,000 credits"},
    "scale": {"credits": 25_000, "price_cents": 20000, "label": "25,000 credits"},
    "enterprise": {"credits": 100_000, "price_cents": 75000, "label": "100,000 credits"},
}


def _stripe_key() -> str:
    key = os.environ.get("STRIPE_API_KEY", "")
    if not key:
        raise ValueError("STRIPE_API_KEY not configured")
    return key


def _webhook_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify Stripe webhook signature (v1 scheme)."""
    if not secret or not sig_header:
        return False

    # Parse timestamp and signatures from header
    elements = dict(item.split("=", 1) for item in sig_header.split(",") if "=" in item)
    timestamp = elements.get("t", "")
    v1_sig = elements.get("v1", "")

    if not timestamp or not v1_sig:
        return False

    # Compute expected signature
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

    # Timing-safe comparison
    return hmac.compare_digest(expected, v1_sig)


@router.post("/v1/checkout")
async def create_checkout(request: Request) -> JSONResponse:
    """Create a Stripe Checkout session for credit purchase.

    Body:
        {"package": "starter"} — use preset package
        {"credits": 5000}      — custom amount ($1 = 100 credits)
    """
    # Authenticate
    raw_key = extract_api_key(request)
    if not raw_key:
        return await error_response(401, "Missing API key", "missing_key")

    ctx = request.app.state.ctx
    try:
        key_info = await ctx.key_manager.validate_key(raw_key)
    except Exception as exc:
        return await handle_product_exception(request, exc)

    agent_id = key_info["agent_id"]

    # Parse body
    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return await error_response(400, "Invalid JSON body", "bad_request")

    # Determine credits and price
    package_name = body.get("package")
    if package_name:
        pkg = PACKAGES.get(package_name)
        if not pkg:
            return await error_response(
                400,
                f"Unknown package: {package_name}. Options: {', '.join(PACKAGES.keys())}",
                "bad_request",
            )
        credits = int(pkg["credits"])
        price_cents = int(pkg["price_cents"])
        label = str(pkg["label"])
    else:
        raw_credits = body.get("credits")
        if not raw_credits or not isinstance(raw_credits, (int, float)) or raw_credits < 100:
            return await error_response(400, "Specify 'package' or 'credits' (minimum 100)", "bad_request")
        credits = int(raw_credits)
        price_cents = int(credits / CREDITS_PER_DOLLAR * 100)
        label = f"{credits:,} credits"

    # Determine URLs
    domain = os.environ.get("A2A_DOMAIN", request.headers.get("host", "localhost"))
    scheme = "https" if "greenhelix" in domain else "http"
    success_url = body.get("success_url", f"{scheme}://{domain}/v1/health")
    cancel_url = body.get("cancel_url", f"{scheme}://{domain}/v1/health")

    # Create Stripe Checkout session
    try:
        stripe_key = _stripe_key()
    except ValueError as e:
        return await error_response(503, str(e), "service_unavailable")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(stripe_key, ""),
                data={
                    "mode": "payment",
                    "payment_method_types[0]": "card",
                    "line_items[0][price_data][currency]": "usd",
                    "line_items[0][price_data][unit_amount]": str(price_cents),
                    "line_items[0][price_data][product_data][name]": f"A2A Credits: {label}",
                    "line_items[0][quantity]": "1",
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "metadata[agent_id]": agent_id,
                    "metadata[credits]": str(credits),
                },
                timeout=15.0,
            )

        if resp.status_code != 200:
            logger.error("Stripe API error: %s %s", resp.status_code, resp.text)
            return await error_response(502, "Failed to create checkout session", "stripe_error")

        session = resp.json()
        return JSONResponse(
            {
                "checkout_url": session["url"],
                "session_id": session["id"],
                "credits": credits,
                "amount_usd": price_cents / 100,
            }
        )

    except httpx.HTTPError as e:
        logger.error("Stripe request failed: %s", e)
        return await error_response(502, "Stripe API unavailable", "stripe_error")


@router.post("/v1/stripe-webhook")
async def stripe_webhook(request: Request) -> JSONResponse:
    """Handle Stripe webhook events.

    On checkout.session.completed → deposit credits to agent's wallet.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = _webhook_secret()

    # Verify signature — mandatory; refuse if secret not configured
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured — refusing webhook")
        return JSONResponse({"error": "Webhook signature verification not configured"}, status_code=503)
    if not _verify_stripe_signature(payload, sig_header, webhook_secret):
        logger.warning("Invalid Stripe webhook signature")
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    # #6 — Validate timestamp to prevent replay of old events
    elements = dict(item.split("=", 1) for item in sig_header.split(",") if "=" in item)
    ts_str = elements.get("t", "")
    if ts_str:
        try:
            ts_val = float(ts_str)
            if abs(time.time() - ts_val) > _MAX_WEBHOOK_AGE_SECONDS:
                logger.warning("Stripe webhook timestamp too old: %s", ts_str)
                return JSONResponse({"error": "Webhook timestamp expired"}, status_code=400)
        except (ValueError, TypeError):
            pass

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    event_type = event.get("type", "")
    logger.info("Stripe webhook: %s", event_type)

    if event_type == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        session_id = session.get("id", "")

        # Deduplicate: DB is the primary source of truth; in-memory set
        # is a performance cache only.  Fail-closed: if DB is unavailable,
        # reject the webhook rather than silently falling back to volatile memory.
        if session_id:
            # 1. In-memory cache (fast path for same-process replays)
            if session_id in _processed_sessions:
                logger.info("Duplicate webhook for session %s — skipping (memory)", session_id)
                return JSONResponse({"received": True})

            # 2. DB check (primary — survives process restarts)
            ctx_check = request.app.state.ctx
            try:
                cursor = await ctx_check.tracker.storage.db.execute(
                    "SELECT 1 FROM processed_stripe_sessions WHERE session_id = ?",
                    (session_id,),
                )
                if await cursor.fetchone():
                    _processed_sessions.add(session_id)  # warm cache
                    logger.info("Duplicate webhook for session %s — skipping (db)", session_id)
                    return JSONResponse({"received": True})
            except Exception:
                logger.error("Stripe dedup DB unavailable — rejecting webhook for safety")
                return JSONResponse({"error": "Dedup database unavailable"}, status_code=503)

        metadata = session.get("metadata", {})
        agent_id = metadata.get("agent_id")
        credits = metadata.get("credits")

        # #26: Validate metadata type safety
        if not agent_id or not isinstance(agent_id, str) or not agent_id.strip():
            logger.warning("Missing or empty agent_id in Stripe webhook metadata")
            return JSONResponse({"error": "Missing agent_id in session metadata"}, status_code=400)

        _MAX_CREDITS = 1_000_000
        if agent_id and credits:
            try:
                credits = int(credits)
            except (ValueError, TypeError):
                logger.warning("Invalid credits value in webhook metadata: %s", credits)
                return JSONResponse({"error": "Invalid credit amount"}, status_code=400)
            if credits <= 0 or credits > _MAX_CREDITS:
                logger.warning("Credits out of range in webhook: %s", credits)
                return JSONResponse({"error": f"Credit amount must be 1-{_MAX_CREDITS}"}, status_code=400)
            ctx = request.app.state.ctx

            try:
                # Ensure wallet exists
                try:
                    await ctx.tracker.wallet.create(agent_id)
                except Exception:
                    pass  # Wallet may already exist

                # Deposit credits
                await ctx.tracker.wallet.deposit(
                    agent_id,
                    float(credits),
                    description=f"Stripe checkout: {credits} credits",
                )
                if session_id:
                    _processed_sessions.add(session_id)
                    try:
                        await ctx.tracker.storage.db.execute(
                            "INSERT OR IGNORE INTO processed_stripe_sessions (session_id, processed_at) VALUES (?, ?)",
                            (session_id, time.time()),
                        )
                        await ctx.tracker.storage.db.commit()
                    except Exception:
                        logger.error("Failed to persist Stripe session dedup for %s", session_id)
                logger.info(
                    "Deposited %d credits to %s (session %s)",
                    credits,
                    agent_id,
                    session_id or "?",
                )
            except Exception:
                logger.exception("Failed to deposit credits for %s", agent_id)
                return JSONResponse({"error": "Deposit failed"}, status_code=500)

    # Always return 200 to acknowledge receipt
    return JSONResponse({"received": True})
