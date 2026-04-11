# A2A Commerce × Cursor

MCP integration for the Cursor editor.

## Install

Edit your Cursor MCP config at `~/.cursor/mcp.json`
(create the file if it doesn't exist):

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

Restart Cursor. Open the Command Palette → **MCP: List Servers** to
confirm `a2a-commerce` is active.

## HTTP transport (remote)

If you prefer Cursor to hit the hosted MCP bridge instead of spawning
a local Node process:

```json
{
  "mcpServers": {
    "a2a-commerce": {
      "url": "https://api.greenhelix.net/mcp",
      "auth": {"type": "bearer", "token": "a2a_free_YOUR_KEY_HERE"}
    }
  }
}
```

The HTTP transport is the same code path — pick stdio for offline
work, HTTP for shared config across machines.

## Try it

Inside a Cursor chat, prompt:

- "Use a2a-commerce to pay the agent that generated this function
   (1 USD via pay_agent)."
- "Show me the current wallet balance from a2a-commerce."

Cursor will surface the tool call UI, you approve, and the result
lands in the chat.

## Further reading

- [Claude Desktop integration](./claude-desktop.md)
- [A2A Commerce API reference](../api-reference.md)
