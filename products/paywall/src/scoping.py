"""API key scoping: tool scope classification and permission checking.

Tools are classified into three scope levels:
- "read": tools that only query data (get_*, search_*, list_*)
- "write": tools that modify state (create_*, send_*, deposit, withdraw, etc.)
- "admin": dangerous/privileged tools (backup_database, restore_database, etc.)

The ScopeChecker enforces allowed_tools, allowed_agent_ids, and scope restrictions.
Designed for extensibility (OCP): new scope types can be added to SCOPE_HIERARCHY
and ADMIN_TOOLS / READ_PREFIXES without modifying existing logic.
"""

from __future__ import annotations

from collections.abc import Sequence


class KeyScopeError(Exception):
    """Raised when a key lacks the required scope or permission."""

    def __init__(self, reason: str = "Scope violation") -> None:
        self.reason = reason
        super().__init__(reason)


# ---------------------------------------------------------------------------
# Scope hierarchy: higher scopes include lower ones
# ---------------------------------------------------------------------------

#: Ordered from least to most privileged.
VALID_SCOPES = ("read", "write", "admin")

#: Scope hierarchy: each scope includes all scopes below it.
SCOPE_HIERARCHY: dict[str, set[str]] = {
    "read": {"read"},
    "write": {"read", "write"},
    "admin": {"read", "write", "admin"},
}

# ---------------------------------------------------------------------------
# Tool → scope classification
# ---------------------------------------------------------------------------

#: Tools that require admin scope (explicit list).
ADMIN_TOOLS: set[str] = {
    "backup_database",
    "restore_database",
    "check_db_integrity",
    "list_backups",
}

#: Prefixes that indicate a read-only tool.
READ_PREFIXES: tuple[str, ...] = (
    "get_",
    "search_",
    "list_",
    "verify_",
    "check_",
    "estimate_",
    "best_match",
    "describe_",
    "explain_",
)

#: Explicit overrides: tool_name → scope.
_TOOL_SCOPE_OVERRIDES: dict[str, str] = {
    # check_db_integrity is admin despite "check_" prefix
    "check_db_integrity": "admin",
    # check_performance_escrow is read despite "check_" prefix — it queries, doesn't mutate
    "check_performance_escrow": "read",
    # check_sla_compliance is read — it queries
    "check_sla_compliance": "read",
}


class ToolScope:
    """Classify tools into read/write/admin scopes."""

    @staticmethod
    def for_tool(tool_name: str) -> str:
        """Return the scope required for a tool.

        Classification rules (in priority order):
        1. Explicit overrides (_TOOL_SCOPE_OVERRIDES)
        2. Admin tools (ADMIN_TOOLS set)
        3. Read prefixes (READ_PREFIXES)
        4. Default: "write"
        """
        # 1. Explicit override
        if tool_name in _TOOL_SCOPE_OVERRIDES:
            return _TOOL_SCOPE_OVERRIDES[tool_name]

        # 2. Admin tools
        if tool_name in ADMIN_TOOLS:
            return "admin"

        # 3. Read-only by prefix
        for prefix in READ_PREFIXES:
            if tool_name.startswith(prefix) or tool_name == prefix:
                return "read"

        # 4. Default to write
        return "write"


class ScopeChecker:
    """Enforce key scoping rules.

    Parameters
    ----------
    scopes : list of str
        The scopes granted to the key (e.g. ["read", "write"]).
    allowed_tools : list of str or None
        If set, only these tools can be called. None = all tools.
    allowed_agent_ids : list of str or None
        If set, only these agent_ids can be operated on. None = all.
    """

    def __init__(
        self,
        scopes: Sequence[str],
        allowed_tools: list[str] | None = None,
        allowed_agent_ids: list[str] | None = None,
    ) -> None:
        self.scopes = set(scopes)
        self.allowed_tools = set(allowed_tools) if allowed_tools is not None else None
        self.allowed_agent_ids = set(allowed_agent_ids) if allowed_agent_ids is not None else None

    # --- Effective scopes (expand hierarchy) ---

    @property
    def effective_scopes(self) -> set[str]:
        """All scopes granted, expanding the hierarchy."""
        result: set[str] = set()
        for s in self.scopes:
            result |= SCOPE_HIERARCHY.get(s, {s})
        return result

    def check_scope(self, tool_name: str) -> None:
        """Raise KeyScopeError if the key lacks the scope required by tool_name."""
        required = ToolScope.for_tool(tool_name)
        if required not in self.effective_scopes:
            raise KeyScopeError(f"Key scope insufficient: tool '{tool_name}' requires '{required}' scope")

    def check_tool(self, tool_name: str) -> None:
        """Raise KeyScopeError if tool_name is not in allowed_tools."""
        if self.allowed_tools is not None and tool_name not in self.allowed_tools:
            raise KeyScopeError(f"Tool '{tool_name}' not in allowed tools for this key")

    def check_agent_id(self, agent_id: str) -> None:
        """Raise KeyScopeError if agent_id is not in allowed_agent_ids."""
        if self.allowed_agent_ids is not None and agent_id not in self.allowed_agent_ids:
            raise KeyScopeError(f"Agent '{agent_id}' not in allowed agent_ids for this key")

    def check_all(self, tool_name: str, agent_id: str | None = None) -> None:
        """Run all scope checks at once."""
        self.check_tool(tool_name)
        self.check_scope(tool_name)
        if agent_id is not None:
            self.check_agent_id(agent_id)
