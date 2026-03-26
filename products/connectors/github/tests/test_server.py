"""Tests for GitHub MCP server setup."""

import json

import pytest
from unittest.mock import AsyncMock, patch

from src.server import TOOL_DEFINITIONS, TOOL_HANDLERS


class TestToolDefinitions:
    def test_all_tools_defined(self):
        tool_names = {t["name"] for t in TOOL_DEFINITIONS}
        expected = {
            "list_repos", "get_repo", "list_issues", "create_issue",
            "list_pull_requests", "get_pull_request", "create_pull_request",
            "list_commits", "get_file_contents", "search_code",
        }
        assert tool_names == expected

    def test_all_tools_have_handlers(self):
        for tool_def in TOOL_DEFINITIONS:
            assert tool_def["name"] in TOOL_HANDLERS, f"Missing handler for {tool_def['name']}"

    def test_all_handlers_have_definitions(self):
        tool_names = {t["name"] for t in TOOL_DEFINITIONS}
        for handler_name in TOOL_HANDLERS:
            assert handler_name in tool_names, f"Missing definition for handler {handler_name}"

    def test_tool_count(self):
        assert len(TOOL_DEFINITIONS) == 10
        assert len(TOOL_HANDLERS) == 10

    def test_tool_definitions_have_schemas(self):
        for tool_def in TOOL_DEFINITIONS:
            assert "inputSchema" in tool_def
            assert "type" in tool_def["inputSchema"]
            assert tool_def["inputSchema"]["type"] == "object"

    def test_tool_definitions_have_descriptions(self):
        for tool_def in TOOL_DEFINITIONS:
            assert "description" in tool_def
            assert len(tool_def["description"]) > 10

    def test_required_fields_for_get_repo(self):
        get_repo = next(t for t in TOOL_DEFINITIONS if t["name"] == "get_repo")
        assert "required" in get_repo["inputSchema"]
        assert "owner" in get_repo["inputSchema"]["required"]
        assert "repo" in get_repo["inputSchema"]["required"]

    def test_required_fields_for_create_issue(self):
        create_issue = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_issue")
        assert "required" in create_issue["inputSchema"]
        assert "owner" in create_issue["inputSchema"]["required"]
        assert "repo" in create_issue["inputSchema"]["required"]
        assert "title" in create_issue["inputSchema"]["required"]

    def test_required_fields_for_create_pr(self):
        create_pr = next(t for t in TOOL_DEFINITIONS if t["name"] == "create_pull_request")
        assert "required" in create_pr["inputSchema"]
        required = create_pr["inputSchema"]["required"]
        assert "owner" in required
        assert "repo" in required
        assert "title" in required
        assert "head" in required
        assert "base" in required


class TestCreateServer:
    @pytest.mark.asyncio
    async def test_create_server(self):
        with patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_test"}):
            from src.server import create_server
            server, client = await create_server()
            assert server is not None
            assert client is not None
            await client.close()
