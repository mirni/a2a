"""MCP server for GitHub connector."""

import json
import logging

from src.client import GitHubClient
from src.tools import (
    handle_create_issue,
    handle_create_pull_request,
    handle_get_file_contents,
    handle_get_pull_request,
    handle_get_repo,
    handle_list_commits,
    handle_list_issues,
    handle_list_pull_requests,
    handle_list_repos,
    handle_search_code,
)

logger = logging.getLogger("a2a.github.server")

TOOL_DEFINITIONS = [
    {
        "name": "list_repos",
        "description": (
            "List repositories for a user/org or the authenticated user. Supports pagination and filtering by type."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {
                    "type": "string",
                    "description": "User or org name. Empty for authenticated user's repos.",
                    "default": "",
                },
                "type": {
                    "type": "string",
                    "description": "Filter: all, owner, public, private, member",
                    "default": "all",
                },
                "sort": {
                    "type": "string",
                    "description": "Sort by: created, updated, pushed, full_name",
                    "default": "updated",
                },
                "page": {"type": "integer", "description": "Page number (1-indexed)", "default": 1},
                "per_page": {
                    "type": "integer",
                    "description": "Results per page (max 100)",
                    "default": 30,
                },
            },
        },
    },
    {
        "name": "get_repo",
        "description": "Get repository metadata including stars, forks, language, and topics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner (user or org)"},
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "list_issues",
        "description": ("List issues for a repository with state, label, and sort filters. Supports pagination."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "state": {
                    "type": "string",
                    "description": "Filter: open, closed, all",
                    "default": "open",
                },
                "labels": {
                    "type": "string",
                    "description": "Comma-separated label names",
                    "default": "",
                },
                "sort": {
                    "type": "string",
                    "description": "Sort by: created, updated, comments",
                    "default": "created",
                },
                "direction": {
                    "type": "string",
                    "description": "Sort direction: asc, desc",
                    "default": "desc",
                },
                "page": {"type": "integer", "default": 1},
                "per_page": {"type": "integer", "default": 30},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "create_issue",
        "description": "Create a new issue with optional labels and assignees.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "title": {"type": "string", "description": "Issue title"},
                "body": {"type": "string", "description": "Issue body (Markdown)", "default": ""},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Label names",
                    "default": [],
                },
                "assignees": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Usernames to assign",
                    "default": [],
                },
            },
            "required": ["owner", "repo", "title"],
        },
    },
    {
        "name": "list_pull_requests",
        "description": ("List pull requests with state, sort, and branch filters. Supports pagination."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "state": {
                    "type": "string",
                    "description": "Filter: open, closed, all",
                    "default": "open",
                },
                "sort": {
                    "type": "string",
                    "description": "Sort by: created, updated, popularity, long-running",
                    "default": "created",
                },
                "direction": {
                    "type": "string",
                    "description": "Sort direction: asc, desc",
                    "default": "desc",
                },
                "head": {
                    "type": "string",
                    "description": "Filter by head branch (user:branch or branch)",
                    "default": "",
                },
                "base": {
                    "type": "string",
                    "description": "Filter by base branch",
                    "default": "",
                },
                "page": {"type": "integer", "default": 1},
                "per_page": {"type": "integer", "default": 30},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "get_pull_request",
        "description": (
            "Get pull request details including diff stats (additions, deletions, changed files) and merge status."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "pull_number": {"type": "integer", "description": "Pull request number"},
            },
            "required": ["owner", "repo", "pull_number"],
        },
    },
    {
        "name": "create_pull_request",
        "description": "Create a pull request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "title": {"type": "string", "description": "PR title"},
                "body": {"type": "string", "description": "PR body (Markdown)", "default": ""},
                "head": {
                    "type": "string",
                    "description": "Branch with changes (user:branch or branch)",
                },
                "base": {"type": "string", "description": "Branch to merge into"},
                "draft": {"type": "boolean", "description": "Create as draft PR", "default": False},
            },
            "required": ["owner", "repo", "title", "head", "base"],
        },
    },
    {
        "name": "list_commits",
        "description": (
            "List commits for a repository with optional branch, path, and date filters. Supports pagination."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "sha": {
                    "type": "string",
                    "description": "SHA or branch to start from",
                    "default": "",
                },
                "path": {
                    "type": "string",
                    "description": "Only commits touching this path",
                    "default": "",
                },
                "since": {
                    "type": "string",
                    "description": "ISO 8601 date — commits after this date",
                    "default": "",
                },
                "until": {
                    "type": "string",
                    "description": "ISO 8601 date — commits before this date",
                    "default": "",
                },
                "page": {"type": "integer", "default": 1},
                "per_page": {"type": "integer", "default": 30},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "get_file_contents",
        "description": (
            "Get file contents from a repository. Automatically decodes base64 content. "
            "Returns directory listing if path points to a directory."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string", "description": "Repository owner"},
                "repo": {"type": "string", "description": "Repository name"},
                "path": {"type": "string", "description": "File path in the repository"},
                "ref": {
                    "type": "string",
                    "description": "Branch, tag, or commit SHA",
                    "default": "",
                },
            },
            "required": ["owner", "repo", "path"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search code across repositories using GitHub code search syntax. "
            "Example query: 'class HTTPClient language:python repo:owner/repo'"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "GitHub code search query"},
                "page": {"type": "integer", "default": 1},
                "per_page": {"type": "integer", "default": 30},
            },
            "required": ["query"],
        },
    },
]

TOOL_HANDLERS = {
    "list_repos": handle_list_repos,
    "get_repo": handle_get_repo,
    "list_issues": handle_list_issues,
    "create_issue": handle_create_issue,
    "list_pull_requests": handle_list_pull_requests,
    "get_pull_request": handle_get_pull_request,
    "create_pull_request": handle_create_pull_request,
    "list_commits": handle_list_commits,
    "get_file_contents": handle_get_file_contents,
    "search_code": handle_search_code,
}


async def create_server():
    """Create and configure the MCP server."""
    from mcp.server import Server

    server = Server("a2a-github")
    client = GitHubClient()

    @server.list_tools()
    async def list_tools():
        from mcp.types import Tool

        return [Tool(**t) for t in TOOL_DEFINITIONS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        from mcp.types import TextContent

        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": True,
                            "code": "UNKNOWN_TOOL",
                            "message": f"Unknown tool: {name}",
                        }
                    ),
                )
            ]

        try:
            result = await handler(client, arguments or {})
            return [TextContent(type="text", text=json.dumps(result, default=str))]
        except Exception as e:
            error_dict = (
                e.to_dict()
                if hasattr(e, "to_dict")
                else {
                    "error": True,
                    "code": "INTERNAL_ERROR",
                    "message": str(e),
                }
            )
            return [TextContent(type="text", text=json.dumps(error_dict))]

    return server, client


async def main():
    """Run the MCP server via stdio transport."""
    from mcp.server.stdio import stdio_server

    server, client = await create_server()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
    finally:
        await client.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
