"""Ownership authorization guard for agent-scoped operations.

Verifies that the API key's agent_id matches any ownership-relevant
parameter in the tool request (agent_id, payer, sender).

Admin-tier keys bypass all ownership checks.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("a2a.authorization")

# Fields that represent "the caller is the actor" — if present in params,
# their value must match the authenticated caller's agent_id.
OWNERSHIP_FIELDS: tuple[str, ...] = ("agent_id", "payer", "sender", "opener", "initiator")

# Tier value that bypasses all ownership checks.
ADMIN_TIER: str = "admin"

# Tools that can only be executed by admin-tier agents.
ADMIN_ONLY_TOOLS: frozenset[str] = frozenset(
    {"resolve_dispute", "freeze_wallet", "unfreeze_wallet", "get_global_audit_log"}
)

# Tools where `agent_id` refers to a target (not the caller).
# The ownership check skips `agent_id` for these tools.
# Trust tools accept `agent_id` as an alias for `server_id`.
AGENT_ID_IS_TARGET: frozenset[str] = frozenset(
    {
        "remove_agent_from_org",
        "add_agent_to_org",
        "get_trust_score",
        "delete_server",
        "update_server",
        "check_sla_compliance",
    }
)


def check_ownership_authorization(
    caller_agent_id: str,
    caller_tier: str,
    params: dict[str, Any],
    tool_name: str = "",
) -> tuple[int, str, str] | None:
    """Check that ownership-relevant params match the caller.

    Returns:
        None if the call is authorized.
        (status_code, message, error_code) if the call is forbidden.
    """
    if caller_tier == ADMIN_TIER:
        return None

    for field in OWNERSHIP_FIELDS:
        # Skip agent_id check for tools where it refers to a target, not the caller
        if field == "agent_id" and tool_name in AGENT_ID_IS_TARGET:
            continue
        value = params.get(field)
        if value is not None and value != caller_agent_id:
            logger.warning(
                "Ownership denied: caller=%s, %s=%s",
                caller_agent_id,
                field,
                value,
            )
            return (
                403,
                f"Forbidden: '{field}' value '{value}' does not match your agent_id '{caller_agent_id}'",
                "forbidden",
            )

    return None
