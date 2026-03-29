"""Billing, wallet, budget, and analytics tool functions."""

from __future__ import annotations

from typing import Any

from gateway.src.lifespan import AppContext
from gateway.src.tool_errors import ToolNotFoundError, ToolValidationError


async def _get_balance(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    balance = await ctx.tracker.get_balance(params["agent_id"])
    return {"balance": balance}


async def _get_usage_summary(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    summary = await ctx.tracker.get_usage_summary(params["agent_id"], since=params.get("since"))
    return summary


async def _deposit(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    new_balance = await ctx.tracker.wallet.deposit(
        params["agent_id"],
        params["amount"],
        description=params.get("description", ""),
    )
    return {"new_balance": new_balance}


async def _get_transactions(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    txns = await ctx.tracker.storage.get_transactions(
        agent_id=params["agent_id"],
        limit=params.get("limit", 100),
        offset=params.get("offset", 0),
    )
    return {"transactions": txns}


async def _create_wallet(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    wallet = await ctx.tracker.wallet.create(
        params["agent_id"],
        initial_balance=params.get("initial_balance", 0.0),
        signup_bonus=params.get("signup_bonus", True),
    )
    return wallet


async def _withdraw(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    new_balance = await ctx.tracker.wallet.withdraw(
        params["agent_id"],
        params["amount"],
        description=params.get("description", ""),
    )
    return {"new_balance": new_balance}


# ---------------------------------------------------------------------------
# Metrics time-series (P2-12)
# ---------------------------------------------------------------------------


async def _get_metrics_timeseries(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Return per-agent usage metrics bucketed by hour or day."""
    agent_id = params["agent_id"]
    interval = params["interval"]  # "hour" or "day"
    since = params.get("since")
    limit = params.get("limit", 24)

    _VALID_INTERVALS = {"hour", "day"}
    if interval not in _VALID_INTERVALS:
        raise ToolValidationError(f"Invalid interval '{interval}': must be one of {sorted(_VALID_INTERVALS)}")

    # Determine the SQL bucket expression
    if interval == "hour":
        bucket_expr = "CAST(CAST(created_at / 3600 AS INTEGER) * 3600 AS REAL)"
    else:
        bucket_expr = "CAST(CAST(created_at / 86400 AS INTEGER) * 86400 AS REAL)"

    query = (
        f"SELECT {bucket_expr} AS bucket, COUNT(*) AS calls, COALESCE(SUM(cost), 0) AS cost "
        f"FROM usage_records WHERE agent_id = ?"
    )
    query_params: list[Any] = [agent_id]

    if since is not None:
        query += " AND created_at >= ?"
        query_params.append(since)

    query += " GROUP BY bucket ORDER BY bucket DESC LIMIT ?"
    query_params.append(limit)

    db = ctx.tracker.storage.db
    cursor = await db.execute(query, query_params)
    rows = await cursor.fetchall()

    buckets = []
    for row in rows:
        buckets.append(
            {
                "timestamp": row[0],
                "calls": row[1],
                "cost": round(row[2], 6),
            }
        )

    buckets.reverse()
    return {"buckets": buckets}


# ---------------------------------------------------------------------------
# Agent leaderboard (P2-13)
# ---------------------------------------------------------------------------


async def _get_agent_leaderboard(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Rank agents by total spend, calls, or trust score."""
    metric = params["metric"]  # "spend", "calls", "trust_score"
    limit = params.get("limit", 10)

    if metric == "spend":
        db = ctx.tracker.storage.db
        cursor = await db.execute(
            "SELECT agent_id, COALESCE(SUM(cost), 0) AS value "
            "FROM usage_records GROUP BY agent_id ORDER BY value DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        leaderboard = [{"rank": i + 1, "agent_id": row[0], "value": round(row[1], 6)} for i, row in enumerate(rows)]
    elif metric == "calls":
        db = ctx.tracker.storage.db
        cursor = await db.execute(
            "SELECT agent_id, COUNT(*) AS value FROM usage_records GROUP BY agent_id ORDER BY value DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        leaderboard = [{"rank": i + 1, "agent_id": row[0], "value": row[1]} for i, row in enumerate(rows)]
    elif metric == "trust_score":
        try:
            db = ctx.identity_api.storage.db
            cursor = await db.execute(
                "SELECT agent_id, composite_score FROM agent_reputation "
                "GROUP BY agent_id "
                "HAVING composite_score = MAX(composite_score) "
                "ORDER BY composite_score DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            leaderboard = [{"rank": i + 1, "agent_id": row[0], "value": round(row[1], 6)} for i, row in enumerate(rows)]
        except (RuntimeError, OSError, AttributeError):
            leaderboard = []
    elif metric == "revenue":
        scale = 100_000_000  # atomic units per credit
        db = ctx.payment_engine.storage.db
        cursor = await db.execute(
            "SELECT payee AS agent_id, CAST(SUM(amount) AS REAL) / ? AS value "
            "FROM settlements GROUP BY payee ORDER BY value DESC LIMIT ?",
            (scale, limit),
        )
        rows = await cursor.fetchall()
        leaderboard = [{"rank": i + 1, "agent_id": row[0], "value": round(row[1], 6)} for i, row in enumerate(rows)]
    elif metric == "rating":
        try:
            db = ctx.marketplace.storage.db
            cursor = await db.execute(
                "SELECT s.provider_id AS agent_id, AVG(r.rating) AS value "
                "FROM service_ratings r "
                "JOIN services s ON r.service_id = s.id "
                "GROUP BY s.provider_id ORDER BY value DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            leaderboard = [{"rank": i + 1, "agent_id": row[0], "value": round(row[1], 6)} for i, row in enumerate(rows)]
        except (RuntimeError, OSError, AttributeError):
            leaderboard = []
    else:
        raise ToolValidationError(f"Unknown metric: {metric}")

    return {"leaderboard": leaderboard}


# ---------------------------------------------------------------------------
# Volume Discount (P3-18)
# ---------------------------------------------------------------------------


def _get_discount_tier(call_count: int) -> int:
    """Return discount percentage based on historical call count.

    Delegates to the billing product pricing module.
    """
    from billing_src.pricing import get_discount_tier

    return get_discount_tier(call_count)


async def _get_volume_discount(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Calculate volume discount based on historical usage."""
    agent_id = params["agent_id"]
    tool_name = params["tool_name"]
    int(params["quantity"])

    usage = await ctx.tracker.storage.get_usage(agent_id, function=tool_name, limit=100000)
    historical_calls = len(usage)

    from gateway.src.catalog import get_tool

    tool_def = get_tool(tool_name)
    unit_price = 0.0
    if tool_def:
        pricing = tool_def.get("pricing", {})
        unit_price = float(pricing.get("per_call", 0.0))

    discount_pct = _get_discount_tier(historical_calls)
    discounted_price = unit_price * (1 - discount_pct / 100)

    return {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "historical_calls": historical_calls,
        "discount_pct": discount_pct,
        "unit_price": unit_price,
        "discounted_price": round(discounted_price, 6),
    }


# ---------------------------------------------------------------------------
# Cost Estimation (P3-19)
# ---------------------------------------------------------------------------


async def _estimate_cost(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Estimate cost of N calls to a tool, with optional volume discount."""
    tool_name = params["tool_name"]
    quantity = int(params["quantity"])
    agent_id = params.get("agent_id")

    from gateway.src.catalog import get_tool

    tool_def = get_tool(tool_name)
    unit_price = 0.0
    if tool_def:
        pricing = tool_def.get("pricing", {})
        unit_price = float(pricing.get("per_call", 0.0))
    else:
        raise ToolNotFoundError(f"Tool not found: {tool_name}")

    discount_pct = 0
    if agent_id:
        usage = await ctx.tracker.storage.get_usage(agent_id, function=tool_name, limit=100000)
        historical_calls = len(usage)
        discount_pct = _get_discount_tier(historical_calls)

    total_cost = unit_price * quantity * (1 - discount_pct / 100)

    return {
        "tool_name": tool_name,
        "quantity": quantity,
        "unit_price": unit_price,
        "discount_pct": discount_pct,
        "total_cost": round(total_cost, 6),
    }


# ---------------------------------------------------------------------------
# Budget Caps (P3-22)
# ---------------------------------------------------------------------------


async def _set_budget_cap(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Set daily/monthly spending caps for an agent."""
    agent_id = params["agent_id"]
    daily_cap = params.get("daily_cap")
    monthly_cap = params.get("monthly_cap")
    alert_threshold = params.get("alert_threshold", 0.8)

    db = ctx.tracker.storage.db
    await db.execute(
        """INSERT INTO budget_caps (agent_id, daily_cap, monthly_cap, alert_threshold)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(agent_id) DO UPDATE SET
             daily_cap = excluded.daily_cap,
             monthly_cap = excluded.monthly_cap,
             alert_threshold = excluded.alert_threshold""",
        (agent_id, daily_cap, monthly_cap, alert_threshold),
    )
    await db.commit()

    return {
        "agent_id": agent_id,
        "daily_cap": daily_cap,
        "monthly_cap": monthly_cap,
        "alert_threshold": alert_threshold,
    }


async def _get_budget_status(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get current spending vs budget caps."""
    import time as _time

    agent_id = params["agent_id"]
    db = ctx.tracker.storage.db

    cursor = await db.execute("SELECT * FROM budget_caps WHERE agent_id = ?", (agent_id,))
    row = await cursor.fetchone()

    daily_cap = row["daily_cap"] if row and row["daily_cap"] is not None else None
    monthly_cap = row["monthly_cap"] if row and row["monthly_cap"] is not None else None
    alert_threshold = row["alert_threshold"] if row else 0.8

    now = _time.time()
    daily_since = now - 86400
    daily_spend = await ctx.tracker.storage.sum_cost_since(agent_id, daily_since)

    monthly_since = now - (30 * 86400)
    monthly_spend = await ctx.tracker.storage.sum_cost_since(agent_id, monthly_since)

    daily_pct = (daily_spend / daily_cap * 100) if daily_cap else 0
    monthly_pct = (monthly_spend / monthly_cap * 100) if monthly_cap else 0

    alert_triggered = False
    cap_exceeded = False

    if daily_cap:
        if daily_spend / daily_cap >= alert_threshold:
            alert_triggered = True
        if daily_spend >= daily_cap:
            cap_exceeded = True

    if monthly_cap:
        if monthly_spend / monthly_cap >= alert_threshold:
            alert_triggered = True
        if monthly_spend >= monthly_cap:
            cap_exceeded = True

    return {
        "agent_id": agent_id,
        "daily_spend": round(daily_spend, 2),
        "daily_cap": daily_cap,
        "daily_pct": round(daily_pct, 2),
        "monthly_spend": round(monthly_spend, 2),
        "monthly_cap": monthly_cap,
        "monthly_pct": round(monthly_pct, 2),
        "alert_triggered": alert_triggered,
        "cap_exceeded": cap_exceeded,
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


async def _get_service_analytics(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get usage analytics for an agent."""
    summary = await ctx.tracker.get_usage_summary(params["agent_id"], since=params.get("since"))
    return {
        "agent_id": params["agent_id"],
        "total_calls": summary.get("total_calls", 0),
        "total_cost": summary.get("total_cost", 0.0),
        "total_tokens": summary.get("total_tokens", 0),
    }


async def _get_revenue_report(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
    """Get revenue report for a provider — aggregates incoming payments."""
    agent_id = params["agent_id"]
    history = await ctx.payment_engine.get_payment_history(agent_id, limit=1000)
    incoming = [h for h in history if h.get("payee") == agent_id and h.get("type") == "settlement"]
    total_revenue = sum(h.get("amount", 0) for h in incoming)
    return {
        "agent_id": agent_id,
        "total_revenue": total_revenue,
        "payment_count": len(incoming),
        "history": incoming[: params.get("limit", 50)],
    }
