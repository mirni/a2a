"""Tool registry: maps tool names to async callables.

Each callable receives (ctx: AppContext, params: dict) and returns a result dict.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from gateway.src.lifespan import AppContext
from gateway.src.tools.billing import (
    _convert_currency,
    _create_wallet,
    _deposit,
    _estimate_cost,
    _freeze_wallet,
    _get_agent_leaderboard,
    _get_balance,
    _get_budget_status,
    _get_exchange_rate,
    _get_metrics_timeseries,
    _get_revenue_report,
    _get_service_analytics,
    _get_transactions,
    _get_usage_summary,
    _get_volume_discount,
    _set_budget_cap,
    _unfreeze_wallet,
    _withdraw,
)
from gateway.src.tools.identity import (
    _add_agent_to_org,
    _build_claim_chain,
    _create_org,
    _get_agent_identity,
    _get_agent_reputation,
    _get_claim_chains,
    _get_metric_averages,
    _get_metric_deltas,
    _get_org,
    _get_verified_claims,
    _ingest_metrics,
    _query_metrics,
    _register_agent,
    _remove_agent_from_org,
    _search_agents_by_metrics,
    _submit_metrics,
    _verify_agent,
)
from gateway.src.tools.infrastructure import (
    _backup_database,
    _check_db_integrity,
    _create_api_key,
    _delete_webhook,
    _get_event_schema,
    _get_events,
    _get_global_audit_log,
    _get_webhook_deliveries,
    _list_api_keys,
    _list_backups,
    _list_webhooks,
    _publish_event,
    _register_event_schema,
    _register_webhook,
    _restore_database,
    _revoke_api_key,
    _rotate_key,
    _test_webhook,
)
from gateway.src.tools.marketplace import (
    _best_match,
    _deactivate_service,
    _get_service,
    _get_service_ratings_tool,
    _list_strategies,
    _rate_service_tool,
    _register_service,
    _search_agents,
    _search_services,
    _update_service,
)
from gateway.src.tools.messaging import (
    _get_messages,
    _negotiate_price,
    _send_message,
)
from gateway.src.tools.payments import (
    _cancel_escrow,
    _cancel_subscription,
    _capture_intent,
    _check_performance_escrow,
    _create_escrow,
    _create_intent,
    _create_performance_escrow,
    _create_split_intent,
    _create_subscription,
    _get_dispute,
    _get_escrow,
    _get_intent,
    _get_payment_history,
    _get_subscription,
    _list_disputes,
    _list_escrows,
    _list_intents,
    _list_subscriptions,
    _open_dispute,
    _partial_capture,
    _process_due_subscriptions,
    _reactivate_subscription,
    _refund_intent,
    _refund_settlement,
    _release_escrow,
    _resolve_dispute,
    _respond_to_dispute,
)
from gateway.src.tools.trust import (
    _check_sla_compliance,
    _delete_server,
    _get_trust_score,
    _register_server,
    _search_servers,
    _update_server,
)

# Type alias for tool functions
ToolFunc = Callable[[AppContext, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]

TOOL_REGISTRY: dict[str, ToolFunc] = {
    # Billing
    "get_balance": _get_balance,
    "get_usage_summary": _get_usage_summary,
    "deposit": _deposit,
    "create_wallet": _create_wallet,
    "withdraw": _withdraw,
    "get_transactions": _get_transactions,
    # Payments
    "create_intent": _create_intent,
    "get_intent": _get_intent,
    "capture_intent": _capture_intent,
    "create_escrow": _create_escrow,
    "get_escrow": _get_escrow,
    "release_escrow": _release_escrow,
    "cancel_escrow": _cancel_escrow,
    "refund_intent": _refund_intent,
    "refund_settlement": _refund_settlement,
    "get_payment_history": _get_payment_history,
    "partial_capture": _partial_capture,
    # Subscriptions
    "create_subscription": _create_subscription,
    "cancel_subscription": _cancel_subscription,
    "get_subscription": _get_subscription,
    "list_subscriptions": _list_subscriptions,
    "reactivate_subscription": _reactivate_subscription,
    # Marketplace
    "search_agents": _search_agents,
    "search_services": _search_services,
    "best_match": _best_match,
    "register_service": _register_service,
    "get_service": _get_service,
    "update_service": _update_service,
    "deactivate_service": _deactivate_service,
    # Trust
    "register_server": _register_server,
    "get_trust_score": _get_trust_score,
    "search_servers": _search_servers,
    "delete_server": _delete_server,
    "update_server": _update_server,
    # Paywall
    "get_global_audit_log": _get_global_audit_log,
    # Event Bus
    "publish_event": _publish_event,
    "get_events": _get_events,
    # Webhooks
    "register_webhook": _register_webhook,
    "list_webhooks": _list_webhooks,
    "delete_webhook": _delete_webhook,
    "get_webhook_deliveries": _get_webhook_deliveries,
    # Scheduler
    "process_due_subscriptions": _process_due_subscriptions,
    # Identity
    "register_agent": _register_agent,
    "verify_agent": _verify_agent,
    "submit_metrics": _submit_metrics,
    "get_agent_identity": _get_agent_identity,
    "get_verified_claims": _get_verified_claims,
    "get_agent_reputation": _get_agent_reputation,
    "search_agents_by_metrics": _search_agents_by_metrics,
    # Performance-gated escrow
    "create_performance_escrow": _create_performance_escrow,
    "check_performance_escrow": _check_performance_escrow,
    # Disputes
    "open_dispute": _open_dispute,
    "respond_to_dispute": _respond_to_dispute,
    "resolve_dispute": _resolve_dispute,
    "get_dispute": _get_dispute,
    "list_disputes": _list_disputes,
    # Key rotation
    "rotate_key": _rotate_key,
    # Historical claims
    "build_claim_chain": _build_claim_chain,
    "get_claim_chains": _get_claim_chains,
    # Messaging
    "send_message": _send_message,
    "get_messages": _get_messages,
    "negotiate_price": _negotiate_price,
    # SLA enforcement
    "check_sla_compliance": _check_sla_compliance,
    # Strategy marketplace
    "list_strategies": _list_strategies,
    # Analytics
    "get_service_analytics": _get_service_analytics,
    "get_revenue_report": _get_revenue_report,
    # Multi-party splits
    "create_split_intent": _create_split_intent,
    # Database security
    "backup_database": _backup_database,
    "restore_database": _restore_database,
    "check_db_integrity": _check_db_integrity,
    "list_backups": _list_backups,
    # P1 features — API Key Management
    "list_api_keys": _list_api_keys,
    "revoke_api_key": _revoke_api_key,
    # P1 features — Exchange Rate
    "get_exchange_rate": _get_exchange_rate,
    "convert_currency": _convert_currency,
    # P2 features
    "get_metrics_timeseries": _get_metrics_timeseries,
    "get_agent_leaderboard": _get_agent_leaderboard,
    "register_event_schema": _register_event_schema,
    "get_event_schema": _get_event_schema,
    "test_webhook": _test_webhook,
    "create_api_key": _create_api_key,
    # P3 features — Volume Discount & Cost Estimation
    "get_volume_discount": _get_volume_discount,
    "estimate_cost": _estimate_cost,
    # P3 features — Service Ratings
    "rate_service": _rate_service_tool,
    "get_service_ratings": _get_service_ratings_tool,
    # P3 features — Budget Caps
    "set_budget_cap": _set_budget_cap,
    "get_budget_status": _get_budget_status,
    # P3 features — Org/Team
    "create_org": _create_org,
    "get_org": _get_org,
    "add_agent_to_org": _add_agent_to_org,
    "remove_agent_from_org": _remove_agent_from_org,
    # List intents/escrows (P2-3)
    "list_intents": _list_intents,
    "list_escrows": _list_escrows,
    # Wallet freeze/unfreeze
    "freeze_wallet": _freeze_wallet,
    "unfreeze_wallet": _unfreeze_wallet,
    # Time-series metrics (PRD 012)
    "ingest_metrics": _ingest_metrics,
    "query_metrics": _query_metrics,
    "get_metric_deltas": _get_metric_deltas,
    "get_metric_averages": _get_metric_averages,
}


# ---------------------------------------------------------------------------
# MCP Connector proxy tools — dynamically registered at startup
# ---------------------------------------------------------------------------


def register_mcp_tools(proxy_manager) -> None:
    """Register proxy tool functions for all MCP connector tools."""
    from gateway.src.mcp_proxy import _TOOL_MAP
    from gateway.src.sql_validator import validate_pg_execute_sql

    for tool_name in _TOOL_MAP:

        def _make_handler(tn: str):
            async def _handler(ctx: AppContext, params: dict[str, Any]) -> dict[str, Any]:
                # Security: validate SQL for pg_execute before proxying
                if tn == "pg_execute":
                    sql = params.get("sql", "")
                    error = validate_pg_execute_sql(sql, params)
                    if error:
                        raise PermissionError(f"pg_execute blocked: {error}")
                return await ctx.mcp_proxy.call_tool(tn, params)

            return _handler

        TOOL_REGISTRY[tool_name] = _make_handler(tool_name)
