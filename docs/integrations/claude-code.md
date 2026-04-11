# A2A Commerce × Claude Code

MCP integration for Anthropic's Claude Code CLI.

## Install

One-liner via `claude mcp add`:

```bash
claude mcp add a2a-commerce npx -y @greenhelix/mcp-server
```

Then set your API key:

```bash
claude mcp set-env a2a-commerce A2A_API_KEY=a2a_free_YOUR_KEY_HERE
```

Verify it's registered:

```bash
claude mcp list
# Expect: a2a-commerce  npx -y @greenhelix/mcp-server  (stdio)
```

## Manual config

If you prefer editing `~/.claude/mcp.json` by hand:

```json
{
  "mcpServers": {
    "a2a-commerce": {
      "command": "npx",
      "args": ["-y", "@greenhelix/mcp-server"],
      "env": {"A2A_API_KEY": "a2a_free_YOUR_KEY_HERE"}
    }
  }
}
```

## Try it

Inside a `claude` session:

```
You: Use a2a-commerce to charge 0.50 USD from my wallet for a
     code-review lookup, then show the balance before/after.
Claude: I'll run pay_agent(...) and get_balance(...)...
```

Claude Code will ask for tool-use approval per-call by default. Run
with `--allowedTools "mcp__a2a-commerce__*"` to auto-approve a
specific server's tools.

## Further reading

- [Claude Code MCP docs](https://docs.claude.com/en/docs/claude-code/mcp)
- [A2A Commerce API reference](../api-reference.md)
