# a2a-greenhelix-mcp-server

<!-- mcp-name: net.greenhelix/mcp-server -->

[![PyPI](https://img.shields.io/pypi/v/a2a-greenhelix-mcp-server.svg)](https://pypi.org/project/a2a-greenhelix-mcp-server/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**MCP server for agent commerce.** Exposes 141 commerce tools — billing,
payments, escrow, identity, marketplace, trust, messaging — from the
[Green Helix A2A Commerce Gateway](https://greenhelix.net) to any
MCP-aware agent (Claude Desktop, Cursor, Claude Code, Windsurf,
LangGraph, CrewAI, ...).

## Install

```bash
pip install a2a-greenhelix-mcp-server
```

Optional HTTP transport:

```bash
pip install 'a2a-greenhelix-mcp-server[http]'
```

## Quickstart — Claude Desktop

1. Get an API key (free tier: 500 credits / 100 req/hr) at
   <https://greenhelix.net>.
2. Edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "a2a": {
      "command": "a2a-greenhelix-mcp-server",
      "env": {
        "A2A_API_KEY": "a2a_free_..."
      }
    }
  }
}
```

3. Restart Claude Desktop. You'll see tools like `create_intent`,
   `create_escrow`, `get_balance`, `negotiate_price` in the tool picker.

## Quickstart — Cursor / Claude Code / Windsurf

Same as Claude Desktop — any MCP-aware IDE accepts the same config.
The server supports both `stdio` (default) and Streamable HTTP
transports.

## Environment variables

| Variable       | Default                        | Description                          |
|----------------|--------------------------------|--------------------------------------|
| `A2A_API_KEY`  | *(required)*                   | Gateway API key. Free tier available. |
| `A2A_BASE_URL` | `https://api.greenhelix.net`   | Override for self-hosted gateway.    |
| `A2A_MCP_TRANSPORT` | `stdio`                   | `stdio` or `http`.                   |
| `A2A_MCP_HOST` | `127.0.0.1`                    | HTTP transport bind host.            |
| `A2A_MCP_PORT` | `8765`                         | HTTP transport bind port.            |

## How it works

* **Tool discovery**: `GET /v1/pricing` returns the full catalog with
  JSON Schemas; this package converts entries into MCP `Tool` objects.
* **Tool invocation**: each `tools/call` is forwarded as a single-item
  `POST /v1/batch`, which in turn dispatches to the gateway's internal
  `TOOL_REGISTRY`.
* **Agent-SEO**: pricing and tier metadata are folded into every tool's
  description so planner LLMs can pick the cheapest or lowest-tier
  alternative.

## Self-hosting

```bash
docker run --rm -it \
  -e A2A_API_KEY=a2a_pro_... \
  -e A2A_BASE_URL=https://api.greenhelix.net \
  greenhelix/a2a-greenhelix-mcp-server:latest
```

Or point at your own gateway:

```bash
A2A_BASE_URL=https://gateway.internal.example.com a2a-greenhelix-mcp-server
```

## License

MIT. See [LICENSE](./LICENSE).
