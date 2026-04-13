# Next Steps: Maximising Agent Reach

**Date:** 2026-04-13
**Context:** Post-v1.4.0 repo review — hygiene done, integration status assessed.

---

## Current State: What's Shipped

| Channel | Package | Version | Status |
|---------|---------|---------|--------|
| PyPI — SDK | `a2a-greenhelix-sdk` | 1.4.0 | Published |
| npm — SDK | `@greenhelix/sdk` | 1.4.0 | Published |
| PyPI — MCP server | `a2a-mcp-server` | 0.1.0 | Published |
| npm — MCP server | `@greenhelix/mcp-server` | 0.1.0 | Published |
| Docker Hub | `greenhelix/a2a-gateway` | latest | Published |
| PyPI — LangChain | `a2a-langchain` | 0.1.0 | Published |
| PyPI — CrewAI | `a2a-crewai` | 0.1.0 | Published |
| IDE docs | claude/cursor/windsurf/zed | — | Shipped |
| `.well-known/*` | 6 endpoints | — | Live on sandbox |
| Agent card | `/.well-known/agent.json` | — | Live on sandbox |
| A2A protocol | agent discovery | — | Live |
| Z3 Gatekeeper | formal verification | — | Live (PR #100) |

**What's NOT shipped yet:**
- MCP Registry listing (DNS verification pending)
- MCP directory submissions (mcp.so, Glama, Smithery, PulseMCP, awesome-mcp-servers)
- A2A registry submissions (a2aregistry.org, a2a.ac)
- LangGraph / CrewAI examples
- Vercel AI SDK wrapper
- LlamaIndex integration
- OpenAI Agents SDK wrapper
- Agent-SEO tool description rewrite
- robots.txt for API (currently website blocks AI crawlers!)
- README badges and quickstart

---

## Priority Actions — ROI-Sorted

### P0: Zero-Code / Config-Only (human actions, <1hr total)

These require **no code** — just human account setup and form submissions.
They're the highest-ROI items because they convert existing published
packages into discoverable listings.

| # | Action | Reach | Blocker |
|---|--------|-------|---------|
| 1 | **MCP Registry DNS verification** — add Ed25519 TXT record to greenhelix.net, set `MCP_REGISTRY_PRIVATE_KEY` secret | ~500K | Human: DNS access |
| 2 | **Submit to mcp.so** — GitHub issue on `chatmcp/mcp-directory` | ~100K | Human: GitHub account |
| 3 | **Submit to Glama** — "Add Server" form at glama.ai/mcp/servers | ~100K | Human: web form |
| 4 | **Smithery** — `npx @smithery/cli publish` with `smithery.yaml` | ~50K | Agent: needs smithery.yaml |
| 5 | **awesome-mcp-servers** — PR to `modelcontextprotocol/servers` | ~80K | Agent: PR |
| 6 | **a2aregistry.org + a2a.ac** — submit agent card URL | ~30K | Human: web form |
| 7 | **GitHub repo topics** — add `mcp`, `a2a`, `agent-payments`, `langchain`, `crewai` | — | Human: repo settings |

### P1: Low-Effort Code Changes (agent, ~1.5 days)

| # | Task | Reach | Effort |
|---|------|-------|--------|
| 8 | **Fix robots.txt** — website currently blocks GPTBot, ClaudeBot, etc. For an agent-facing product, these should be allowed. Add gateway-side robots.txt allowing all agent crawlers | ~300K boost | 0.1d |
| 9 | **Agent-SEO: tool description rewrite** — rewrite all 128 tool descriptions with structured `<verb> <object>. Accepts <params>. Returns <output>. Ideal when <trigger>. Price: <cost>.` template | ~300K boost | 0.5d |
| 10 | **LangGraph example** — `integrations/langchain/examples/langgraph_agent.py` showing buyer→seller payment flow | ~100K | 0.25d |
| 11 | **CrewAI marketplace example** — `integrations/crewai/examples/marketplace_crew.py` | ~50K | 0.25d |
| 12 | **README overhaul** — add badges (PyPI, npm, Docker pulls), 30-second quickstart, "Install in Claude" button | — | 0.25d |
| 13 | **smithery.yaml** — add config file so `npx @smithery/cli publish` works | ~50K | 0.1d |

### P2: New Framework Wrappers (agent, ~3 days)

| # | Task | Reach | Effort | Notes |
|---|------|-------|--------|-------|
| 14 | **Vercel AI SDK** — `@greenhelix/vercel-ai-tools` npm package | ~150K | 0.5d | Huge Next.js/Vercel ecosystem |
| 15 | **LlamaIndex** — `integrations/llamaindex/` with `A2AToolSpec` | ~100K | 1.0d | Submit to llama-index-integrations |
| 16 | **OpenAI Agents SDK** — wrapper for `openai.agents` tool format | ~200K | 0.5d | Fast-growing, official OpenAI |
| 17 | **Google ADK** — manifest for Agent Development Kit | ~100K | 0.5d | Google's new agent framework |
| 18 | **AutoGen** — deprioritized (Microsoft merger churn), track only | ~50K | 0.5d | Hold unless ecosystem stabilizes |

### P3: Content & Community (agent + human, ~2 days)

| # | Task | Reach | Effort |
|---|------|-------|--------|
| 19 | **dev.to tutorial series** — "Agent Payments in 5 Minutes", "Building a Marketplace Crew", "Escrow for AI Contracts" | ~50K/post | 1.5d |
| 20 | **Distribution metrics script** — `scripts/collect_distribution_metrics.py` pulling PyPI/npm/Docker download counts | tracking | 0.25d |
| 21 | **Product Hunt launch** — create page, schedule launch | ~50K burst | Human |
| 22 | **Hacker News Show HN** | ~30K burst | Human |

---

## Critical Bug: robots.txt Blocks Agent Discovery

The website `robots.txt` currently **disallows** GPTBot, ChatGPT-User,
Google-Extended, CCBot, and anthropic-ai. For a product whose customers
ARE AI agents, this is self-defeating. The API gateway has no robots.txt
at all (defaults to allow-all, which is correct).

**Fix:** Flip the website robots.txt to allow agent crawlers. The API
gateway should serve a permissive robots.txt explicitly.

---

## Recommended Sprint Plan

**Week 1 (April 14-18):**
- Human: DNS verification for MCP Registry (#1)
- Human: Submit to mcp.so, Glama, a2aregistry.org (#2, #3, #6)
- Agent: Fix robots.txt (#8)
- Agent: Agent-SEO tool descriptions (#9)
- Agent: smithery.yaml + publish (#13)
- Agent: awesome-mcp-servers PR (#5)
- Agent: README overhaul (#12)

**Week 2 (April 21-25):**
- Agent: LangGraph + CrewAI examples (#10, #11)
- Agent: Vercel AI SDK wrapper (#14)
- Agent: OpenAI Agents SDK wrapper (#16)
- Agent: Distribution metrics script (#20)

**Week 3 (April 28-May 2):**
- Agent: LlamaIndex integration (#15)
- Agent: dev.to tutorial series (#19)
- Human: Product Hunt launch prep (#21)

---

## Unique Differentiator: Z3 Gatekeeper

No competing A2A platform ships formal verification. This should be
prominently featured in every listing, tool description, and example:

> "The only commerce platform with Z3-based formal verification —
> mathematically prove payment invariants before execution."

Surface this in: MCP server description, registry listings, README,
website hero section, Agent-SEO tool descriptions.
