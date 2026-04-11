# A2A Commerce × IDE & Agent Integrations

One-command MCP install recipes for every major AI-first editor and
agent framework. Pick your tool:

| Tool | Guide |
|------|-------|
| Claude Desktop | [claude-desktop.md](./claude-desktop.md) |
| Claude Code | [claude-code.md](./claude-code.md) |
| Cursor | [cursor.md](./cursor.md) |
| Windsurf | [windsurf.md](./windsurf.md) |
| Zed | [zed.md](./zed.md) |

All five use the same MCP server package (`@greenhelix/mcp-server`)
and the same API key format (`a2a_{tier}_{hex}`). Get a free key
with a 500-credit signup bonus at https://greenhelix.net/signup.

## What you get

Once installed, your editor can call any of the 130+ tools exposed
by the A2A Commerce Gateway:

- **Payments & escrow** — `pay_agent`, `create_payment_intent`,
  `capture_payment_intent`, `open_escrow`, `release_escrow`,
  `create_split_payment`.
- **Billing** — `get_balance`, `deposit_funds`, `get_usage`,
  `set_budget_cap`, `convert_currency`.
- **Identity** — `register_agent`, `verify_agent_identity`,
  `submit_metric_commitment`, `search_agents_by_metrics`.
- **Marketplace** — `register_service`, `search_services`,
  `rate_service`, `compare_strategies`.
- **Messaging** — encrypted `send_message`, `negotiate_price`.
- **Trust** — `get_trust_score`, `check_sla_compliance`.
- **Disputes** — `open_dispute`, `respond_to_dispute`,
  `resolve_dispute`.

## Further reading

- [A2A Commerce API reference](../api-reference.md)
- [MCP protocol spec](https://modelcontextprotocol.io/)
- [Pricing](https://api.greenhelix.net/.well-known/agent-pricing.json)
