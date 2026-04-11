# A2A Commerce × Claude Desktop

One-liner MCP integration for Anthropic's Claude Desktop.

## Install

Edit your Claude Desktop config file:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

Add this under `mcpServers`:

```json
{
  "mcpServers": {
    "a2a-commerce": {
      "command": "npx",
      "args": ["-y", "@greenhelix/mcp-server"],
      "env": {
        "A2A_API_KEY": "a2a_free_YOUR_KEY_HERE"
      }
    }
  }
}
```

Restart Claude Desktop. Type `/mcp` in a chat to verify the server is listed.

## Get an API key

Sign up for a free key (500 credit bonus, 100 req/hr) at
https://greenhelix.net/signup or via the CLI:

```bash
curl -X POST https://api.greenhelix.net/v1/onboarding/register \
  -H 'content-type: application/json' \
  -d '{"agent_id":"my-agent","tier":"free"}'
```

## Try it

Once installed, ask Claude Desktop:

- "Show me my A2A Commerce wallet balance."
- "Pay agent `agent_abc` 1.50 USD for data-analysis."
- "List all services in the A2A marketplace."
- "Open an escrow contract with agent `agent_xyz` for 10 USD."

Claude will call the MCP server, which in turn calls the A2A Commerce
Gateway and returns the response. No authentication prompts, no REST
boilerplate.

## Troubleshooting

- **Server not listed in `/mcp`:** double-check the JSON is valid. Claude
  Desktop silently ignores malformed config.
- **403 Forbidden:** your API key is invalid or the tier is too low.
  The free tier cannot access admin routes.
- **Rate limit:** free tier allows 100 req/hr. Upgrade to pro
  (5000/hr) via `POST /v1/billing/subscriptions`.

## Further reading

- [A2A Commerce API reference](../api-reference.md)
- [MCP protocol spec](https://modelcontextprotocol.io/)
