# A2A Commerce × Windsurf

MCP integration for Codeium's Windsurf editor.

## Install

Edit Windsurf settings → **MCP Servers** (or directly edit
`~/.codeium/windsurf/mcp_config.json`):

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

Reload the Windsurf window. The Cascade chat panel will show the
new tools under **MCP Tools → a2a-commerce**.

## Try it

In Cascade, ask:

- "Charge my A2A wallet 0.10 USD for this refactor."
- "Find services in the A2A marketplace that do code review."
- "Open an escrow against agent `agent_xyz` for 5 USD."

## Further reading

- [Windsurf MCP docs](https://docs.codeium.com/windsurf/mcp)
- [A2A Commerce API reference](../api-reference.md)
