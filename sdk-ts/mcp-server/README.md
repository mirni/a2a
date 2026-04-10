# @greenhelix/mcp-server

[![npm](https://img.shields.io/npm/v/@greenhelix/mcp-server.svg)](https://www.npmjs.com/package/@greenhelix/mcp-server)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**MCP server for agent commerce.** Exposes 141 commerce tools — billing,
payments, escrow, identity, marketplace, trust, messaging — from the
[Green Helix A2A Commerce Gateway](https://greenhelix.net) to any
MCP-aware agent (Claude Desktop, Cursor, Claude Code, Windsurf, ...).

## Install

```bash
npm install -g @greenhelix/mcp-server
# or run with npx (no install needed):
npx -y @greenhelix/mcp-server
```

## Quickstart — Claude Desktop

1. Get a free API key (500 credits, 100 req/hr) at <https://greenhelix.net>.
2. Edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "a2a": {
      "command": "npx",
      "args": ["-y", "@greenhelix/mcp-server"],
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

Same config as Claude Desktop — any MCP-aware IDE accepts it.

## Environment variables

| Variable       | Default                        | Description                          |
|----------------|--------------------------------|--------------------------------------|
| `A2A_API_KEY`  | *(required)*                   | Gateway API key. Free tier available. |
| `A2A_BASE_URL` | `https://api.greenhelix.net`   | Override for self-hosted gateway.    |

## How it works

* **Tool discovery** via `GET /v1/pricing` — the gateway publishes the
  full catalog with JSON Schemas.
* **Tool invocation** via `POST /v1/batch` — each MCP `tools/call`
  becomes a single-item batch, dispatched to the gateway's
  `TOOL_REGISTRY`.
* **Agent-SEO** — pricing and tier metadata are folded into each tool's
  description so planner LLMs can pick the cheapest alternative.

## License

MIT.
