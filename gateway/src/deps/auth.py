"""Auth dependency: API key extraction and validation."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from gateway.src.auth import extract_api_key
from gateway.src.authorization import ADMIN_TIER


async def authenticate(request: Request) -> tuple[str, str, dict[str, Any] | None]:
    """Extract and validate API key from request.

    Returns (agent_id, agent_tier, key_info) or raises an HTTP error response.
    """
    raw_key = extract_api_key(request)
    if not raw_key:
        raise AuthError(401, "Missing API key", "missing_key")

    ctx = request.app.state.ctx
    try:
        key_info = await ctx.key_manager.validate_key(raw_key)
    except Exception as exc:
        from gateway.src.errors import handle_product_exception

        resp = await handle_product_exception(request, exc)
        raise AuthError(resp.status_code, str(exc), "authentication_error") from exc

    agent_id = key_info["agent_id"]
    agent_tier = key_info["tier"]

    # Promote effective tier to admin when the key carries an admin scope.
    key_scopes = key_info.get("scopes", ["read", "write"])
    if "admin" in key_scopes:
        agent_tier = ADMIN_TIER

    return agent_id, agent_tier, key_info


async def check_scopes(
    request: Request,
    key_info: dict[str, Any],
    tool_name: str,
    params: dict[str, Any],
) -> None:
    """Enforce key scoping (allowed_tools, allowed_agent_ids, scopes)."""
    from paywall_src.scoping import KeyScopeError, ScopeChecker

    scope_checker = ScopeChecker(
        scopes=key_info.get("scopes", ["read", "write"]),
        allowed_tools=key_info.get("allowed_tools"),
        allowed_agent_ids=key_info.get("allowed_agent_ids"),
    )
    try:
        scope_checker.check_tool(tool_name)
        scope_checker.check_scope(tool_name)

        from gateway.src.authorization import AGENT_ID_IS_TARGET

        target_agent = params.get("agent_id")
        if target_agent is not None and tool_name not in AGENT_ID_IS_TARGET:
            scope_checker.check_agent_id(target_agent)
    except KeyScopeError as exc:
        raise AuthError(403, exc.reason, "scope_violation") from exc


class AuthError(Exception):
    """Raised when authentication or authorization fails."""

    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
