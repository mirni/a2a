"""Tests for MCP server registry (TDD).

The registry replaces hardcoded connector config with a data-driven approach:
- Register/unregister MCP connectors
- Enable/disable connectors at runtime
- List registered connectors and their tools
- Persist registry to JSON file
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

pytestmark = pytest.mark.asyncio


class TestConnectorConfig:
    """Test ConnectorConfig model validation."""

    def test_create_connector_config(self):
        from gateway.src.mcp_registry import ConnectorConfig

        cfg = ConnectorConfig(
            name="stripe",
            prefix="stripe",
            tools=["stripe_list_customers", "stripe_create_customer"],
            connector_type="npx",
            enabled=True,
        )
        assert cfg.name == "stripe"
        assert cfg.prefix == "stripe"
        assert len(cfg.tools) == 2
        assert cfg.connector_type == "npx"
        assert cfg.enabled is True

    def test_config_defaults(self):
        from gateway.src.mcp_registry import ConnectorConfig

        cfg = ConnectorConfig(
            name="test",
            prefix="test",
            tools=["test_foo"],
        )
        assert cfg.enabled is True
        assert cfg.connector_type == "python"
        assert cfg.env_vars == {}
        assert cfg.metadata == {}

    def test_config_with_env_vars(self):
        from gateway.src.mcp_registry import ConnectorConfig

        cfg = ConnectorConfig(
            name="stripe",
            prefix="stripe",
            tools=["stripe_list_customers"],
            env_vars={"STRIPE_API_KEY": "required"},
        )
        assert cfg.env_vars["STRIPE_API_KEY"] == "required"

    def test_config_schema_extra(self):
        from gateway.src.mcp_registry import ConnectorConfig

        examples = ConnectorConfig.model_config.get("json_schema_extra", {}).get("examples", [])
        assert len(examples) >= 1


class TestMCPRegistry:
    """Test MCPRegistry register/unregister/list."""

    def test_register_connector(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        cfg = ConnectorConfig(
            name="test-connector",
            prefix="tc",
            tools=["tc_tool_a", "tc_tool_b"],
        )
        registry.register(cfg)
        assert "test-connector" in registry.list_connectors()

    def test_register_duplicate_raises(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        cfg = ConnectorConfig(name="dup", prefix="dup", tools=["dup_a"])
        registry.register(cfg)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(cfg)

    def test_unregister_connector(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        cfg = ConnectorConfig(name="temp", prefix="tmp", tools=["tmp_x"])
        registry.register(cfg)
        registry.unregister("temp")
        assert "temp" not in registry.list_connectors()

    def test_unregister_nonexistent_raises(self):
        from gateway.src.mcp_registry import MCPRegistry

        registry = MCPRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.unregister("ghost")

    def test_get_connector(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        cfg = ConnectorConfig(name="fetch", prefix="ft", tools=["ft_a"])
        registry.register(cfg)
        result = cfg = registry.get("fetch")
        assert result.name == "fetch"

    def test_get_nonexistent_returns_none(self):
        from gateway.src.mcp_registry import MCPRegistry

        registry = MCPRegistry()
        assert registry.get("nope") is None

    def test_list_connectors(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        for name in ["alpha", "beta", "gamma"]:
            registry.register(ConnectorConfig(name=name, prefix=name[0], tools=[f"{name[0]}_x"]))
        names = registry.list_connectors()
        assert set(names) == {"alpha", "beta", "gamma"}


class TestRegistryToolMap:
    """Test tool map generation from registry."""

    def test_build_tool_map(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(
            name="stripe", prefix="stripe",
            tools=["stripe_list_customers", "stripe_create_customer"],
        ))
        registry.register(ConnectorConfig(
            name="github", prefix="github",
            tools=["github_list_repos"],
        ))
        tool_map = registry.build_tool_map()
        assert tool_map["stripe_list_customers"] == ("stripe", "list_customers")
        assert tool_map["stripe_create_customer"] == ("stripe", "create_customer")
        assert tool_map["github_list_repos"] == ("github", "list_repos")

    def test_tool_map_skips_disabled(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(
            name="active", prefix="act", tools=["act_foo"], enabled=True,
        ))
        registry.register(ConnectorConfig(
            name="inactive", prefix="inact", tools=["inact_bar"], enabled=False,
        ))
        tool_map = registry.build_tool_map()
        assert "act_foo" in tool_map
        assert "inact_bar" not in tool_map

    def test_tool_map_with_pg_prefix(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(
            name="postgres", prefix="pg",
            tools=["pg_query", "pg_execute"],
        ))
        tool_map = registry.build_tool_map()
        assert tool_map["pg_query"] == ("postgres", "query")
        assert tool_map["pg_execute"] == ("postgres", "execute")

    def test_get_all_tool_names(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(
            name="a", prefix="a", tools=["a_x", "a_y"],
        ))
        registry.register(ConnectorConfig(
            name="b", prefix="b", tools=["b_z"],
        ))
        all_tools = registry.get_all_tool_names()
        assert set(all_tools) == {"a_x", "a_y", "b_z"}


class TestRegistryEnableDisable:
    """Test enable/disable connector operations."""

    def test_disable_connector(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(name="s", prefix="s", tools=["s_a"]))
        registry.disable("s")
        cfg = registry.get("s")
        assert cfg.enabled is False

    def test_enable_connector(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(name="s", prefix="s", tools=["s_a"], enabled=False))
        registry.enable("s")
        cfg = registry.get("s")
        assert cfg.enabled is True

    def test_disable_nonexistent_raises(self):
        from gateway.src.mcp_registry import MCPRegistry

        registry = MCPRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.disable("ghost")

    def test_enable_nonexistent_raises(self):
        from gateway.src.mcp_registry import MCPRegistry

        registry = MCPRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.enable("ghost")


class TestRegistryPersistence:
    """Test saving/loading registry from JSON file."""

    def test_save_and_load(self):
        from gateway.src.mcp_registry import ConnectorConfig, MCPRegistry

        registry = MCPRegistry()
        registry.register(ConnectorConfig(
            name="stripe", prefix="stripe",
            tools=["stripe_list_customers"],
            connector_type="npx",
            env_vars={"STRIPE_API_KEY": "required"},
        ))
        registry.register(ConnectorConfig(
            name="pg", prefix="pg",
            tools=["pg_query"],
            connector_type="python",
        ))

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name

        try:
            registry.save(path)

            loaded = MCPRegistry.load(path)
            assert set(loaded.list_connectors()) == {"stripe", "pg"}
            stripe_cfg = loaded.get("stripe")
            assert stripe_cfg.connector_type == "npx"
            assert stripe_cfg.env_vars["STRIPE_API_KEY"] == "required"
        finally:
            os.unlink(path)

    def test_load_nonexistent_returns_empty(self):
        from gateway.src.mcp_registry import MCPRegistry

        registry = MCPRegistry.load("/tmp/nonexistent_registry_12345.json")
        assert registry.list_connectors() == []

    def test_load_from_default_creates_builtin(self):
        """Loading default registry should have stripe, github, postgres."""
        from gateway.src.mcp_registry import MCPRegistry

        registry = MCPRegistry.create_default()
        names = set(registry.list_connectors())
        assert names == {"stripe", "github", "postgres"}
        # Verify tool counts match existing hardcoded lists
        assert len(registry.get("stripe").tools) == 13
        assert len(registry.get("github").tools) == 10
        assert len(registry.get("postgres").tools) == 6
