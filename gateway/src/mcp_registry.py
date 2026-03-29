"""MCP server registry — data-driven connector configuration.

Replaces hardcoded tool lists in mcp_proxy.py with a registry that supports:
- Register/unregister MCP connectors
- Enable/disable connectors at runtime
- Build tool maps dynamically
- Persist/load from JSON
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("a2a.mcp_registry")


class ConnectorConfig(BaseModel):
    """Configuration for a single MCP connector."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "stripe",
                    "prefix": "stripe",
                    "tools": ["stripe_list_customers", "stripe_create_customer"],
                    "connector_type": "npx",
                    "enabled": True,
                    "env_vars": {"STRIPE_API_KEY": "required"},
                    "metadata": {},
                }
            ]
        }
    )

    name: str
    prefix: str
    tools: list[str]
    connector_type: str = "python"  # "python" or "npx"
    enabled: bool = True
    env_vars: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPRegistry:
    """Registry of MCP connector configurations."""

    def __init__(self) -> None:
        self._connectors: dict[str, ConnectorConfig] = {}

    def register(self, config: ConnectorConfig) -> None:
        """Register a new connector configuration."""
        if config.name in self._connectors:
            raise ValueError(f"Connector '{config.name}' already registered")
        self._connectors[config.name] = config

    def unregister(self, name: str) -> None:
        """Unregister a connector by name."""
        if name not in self._connectors:
            raise KeyError(f"Connector '{name}' not registered")
        del self._connectors[name]

    def get(self, name: str) -> ConnectorConfig | None:
        """Get connector config by name, or None if not found."""
        return self._connectors.get(name)

    def list_connectors(self) -> list[str]:
        """List all registered connector names."""
        return list(self._connectors.keys())

    def enable(self, name: str) -> None:
        """Enable a connector."""
        if name not in self._connectors:
            raise KeyError(f"Connector '{name}' not registered")
        self._connectors[name].enabled = True

    def disable(self, name: str) -> None:
        """Disable a connector."""
        if name not in self._connectors:
            raise KeyError(f"Connector '{name}' not registered")
        self._connectors[name].enabled = False

    def build_tool_map(self) -> dict[str, tuple[str, str]]:
        """Build gateway_tool_name → (connector_name, mcp_tool_name) map.

        Only includes enabled connectors. Strips prefix from tool names.
        """
        tool_map: dict[str, tuple[str, str]] = {}
        for cfg in self._connectors.values():
            if not cfg.enabled:
                continue
            for tool in cfg.tools:
                mcp_name = tool.replace(f"{cfg.prefix}_", "", 1)
                tool_map[tool] = (cfg.name, mcp_name)
        return tool_map

    def get_all_tool_names(self) -> list[str]:
        """Get all tool names from enabled connectors."""
        names: list[str] = []
        for cfg in self._connectors.values():
            if cfg.enabled:
                names.extend(cfg.tools)
        return names

    def save(self, path: str) -> None:
        """Save registry to a JSON file."""
        data = {
            name: cfg.model_dump()
            for name, cfg in self._connectors.items()
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> MCPRegistry:
        """Load registry from a JSON file. Returns empty registry if file missing."""
        registry = cls()
        if not os.path.exists(path):
            return registry
        with open(path) as f:
            data = json.load(f)
        for name, cfg_data in data.items():
            registry._connectors[name] = ConnectorConfig(**cfg_data)
        return registry

    @classmethod
    def create_default(cls) -> MCPRegistry:
        """Create registry with the built-in connectors (stripe, github, postgres)."""
        registry = cls()
        registry.register(ConnectorConfig(
            name="stripe",
            prefix="stripe",
            connector_type="npx",
            env_vars={"STRIPE_API_KEY": "required"},
            tools=[
                "stripe_list_customers",
                "stripe_create_customer",
                "stripe_list_products",
                "stripe_create_product",
                "stripe_list_prices",
                "stripe_create_price",
                "stripe_create_payment_link",
                "stripe_list_invoices",
                "stripe_create_invoice",
                "stripe_list_subscriptions",
                "stripe_cancel_subscription",
                "stripe_create_refund",
                "stripe_retrieve_balance",
            ],
        ))
        registry.register(ConnectorConfig(
            name="github",
            prefix="github",
            connector_type="python",
            env_vars={"GITHUB_TOKEN": "required"},
            tools=[
                "github_list_repos",
                "github_get_repo",
                "github_list_issues",
                "github_create_issue",
                "github_list_pull_requests",
                "github_get_pull_request",
                "github_create_pull_request",
                "github_list_commits",
                "github_get_file_contents",
                "github_search_code",
            ],
        ))
        registry.register(ConnectorConfig(
            name="postgres",
            prefix="pg",
            connector_type="python",
            env_vars={"POSTGRES_DSN": "required"},
            tools=[
                "pg_query",
                "pg_execute",
                "pg_list_tables",
                "pg_describe_table",
                "pg_explain_query",
                "pg_list_schemas",
            ],
        ))
        return registry
