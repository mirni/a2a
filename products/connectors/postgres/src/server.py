"""MCP server for PostgreSQL connector."""

import json
import logging

from src.client import PostgresClient
from src.tools import (
    handle_describe_table,
    handle_execute,
    handle_explain_query,
    handle_list_schemas,
    handle_list_tables,
    handle_query,
)

logger = logging.getLogger("a2a.postgres.server")

TOOL_DEFINITIONS = [
    {
        "name": "query",
        "description": (
            "Execute a read-only SQL SELECT query. Uses parameterized queries ($1, $2, ...) "
            "to prevent SQL injection. Returns up to max_rows rows."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL SELECT query with $1, $2, ... parameter placeholders",
                },
                "params": {
                    "type": "array",
                    "description": "Positional query parameters",
                    "default": [],
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Query timeout in seconds (max 300)",
                    "default": 30.0,
                },
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum rows to return (max 10000)",
                    "default": 1000,
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "execute",
        "description": (
            "Execute a write SQL statement (INSERT, UPDATE, DELETE). "
            "Requires write mode to be enabled. Uses parameterized queries."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "SQL INSERT/UPDATE/DELETE with $1, $2, ... parameters",
                },
                "params": {
                    "type": "array",
                    "description": "Positional query parameters",
                    "default": [],
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Statement timeout in seconds",
                    "default": 30.0,
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "list_tables",
        "description": "List all tables in a database schema.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "schema_name": {
                    "type": "string",
                    "description": "Schema name",
                    "default": "public",
                },
            },
        },
    },
    {
        "name": "describe_table",
        "description": "Get column names, types, constraints, and defaults for a table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table_name": {"type": "string", "description": "Table name"},
                "schema_name": {
                    "type": "string",
                    "description": "Schema name",
                    "default": "public",
                },
            },
            "required": ["table_name"],
        },
    },
    {
        "name": "explain_query",
        "description": "Get the execution plan for a SQL query (EXPLAIN).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query to explain"},
                "params": {
                    "type": "array",
                    "description": "Query parameters",
                    "default": [],
                },
                "analyze": {
                    "type": "boolean",
                    "description": "Run EXPLAIN ANALYZE (executes the query)",
                    "default": False,
                },
            },
            "required": ["sql"],
        },
    },
    {
        "name": "list_schemas",
        "description": "List all available database schemas.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]

TOOL_HANDLERS = {
    "query": handle_query,
    "execute": handle_execute,
    "list_tables": handle_list_tables,
    "describe_table": handle_describe_table,
    "explain_query": handle_explain_query,
    "list_schemas": handle_list_schemas,
}


async def create_server():
    """Create and configure the MCP server."""
    from mcp.server import Server

    server = Server("a2a-postgres")
    client = PostgresClient()

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
        await client.connect()
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream)
    finally:
        await client.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
