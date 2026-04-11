# A2A Commerce × Zed

MCP integration for the Zed editor.

## Install

Zed supports MCP via the **Context Server** extension system.

1. Open Zed settings (`cmd+,` on macOS, `ctrl+,` elsewhere).
2. Add to your `settings.json` under `context_servers`:

```json
{
  "context_servers": {
    "a2a-commerce": {
      "command": {
        "path": "npx",
        "args": ["-y", "@greenhelix/mcp-server"],
        "env": {"A2A_API_KEY": "a2a_free_YOUR_KEY_HERE"}
      }
    }
  }
}
```

3. Reload Zed (`cmd+shift+p` → **Reload**).
4. Open the AI panel (`cmd+?`) — the A2A Commerce tools will
   appear under the ⚡ icon.

## Try it

In the Zed AI panel:

```
You: Use a2a-commerce to show my wallet balance and list the
     top 5 services in the marketplace.
```

## Further reading

- [Zed context servers](https://zed.dev/docs/assistant/context-servers)
- [A2A Commerce API reference](../api-reference.md)
