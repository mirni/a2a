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
OWNERSHIP_FIELDS: tuple[str, ...] = ("agent_id", "payer", "sender")

# Tier value that bypasses all ownership checks.
ADMIN_TIER: str = "admin"


def check_ownership_authorization(
    caller_agent_id: str,
    caller_tier: str,
    params: dict[str, Any],
) -> tuple[int, str, str] | None:
    """Check that ownership-relevant params match the caller.

    Returns:
        None if the call is authorized.
        (status_code, message, error_code) if the call is forbidden.
    """
    if caller_tier == ADMIN_TIER:
        return None

    for field in OWNERSHIP_FIELDS:
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
