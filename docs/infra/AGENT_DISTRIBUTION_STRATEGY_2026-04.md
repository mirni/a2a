# Agent Distribution Strategy — Green Helix A2A Platform

**Date:** 2026-04-10
**Author:** Growth Strategist Agent
**Horizon:** 2026 Q2 → 2027 Q2
**Status:** Strategic plan — pending human review

---

## 0. Executive Summary

Green Helix ships a production-grade A2A (Agent-to-Agent) commerce gateway —
141 tools, 15 services, dual SDKs, Stripe fiat on-ramp, live sandbox, agent
card, Python + TypeScript + Docker all published. Technical readiness is not
the constraint; **agent discoverability** is.

The thesis of this plan: in 2026–2027, autonomous agents will discover
services through a **three-layer stack**:

1. **Protocol layer** — MCP, A2A Protocol, Agent Commerce Kit, ACP, agents.json
2. **Registry layer** — mcp.so, Glama, Smithery, PulseMCP, a2aregistry.org
3. **Framework layer** — LangChain, LangGraph, CrewAI, Vercel AI SDK, Google ADK,
   OpenAI Agents SDK, Claude Agent SDK, Cursor, Windsurf, Zed

A planner-LLM decides which backend fulfils a task by **reading structured
metadata** — not by consulting a sales funnel. Our job is therefore less
"marketing" and more **search-engine optimisation for machines**: make sure
the right protocol manifests exist, pricing is machine-readable, reputational
signals are cryptographically verifiable, and we appear in the top-N results
of whatever tool-resolver the agent framework uses.

The plan below is organised for ruthless ROI. **70%+ of the expected reach
comes from ~10 zero-cost artefacts** that we can ship in a single sprint.

---

## 1. Product State Delta (vs. DISTRIBUTION.md v0.5.0)

Changes since the v0.5.0 distribution plan (2026-04-02):

| Capability | Previous | Current |
|------------|----------|---------|
| PyPI `a2a-greenhelix-sdk` | not published | **v1.2.1 live** |
| npm `@greenhelix/sdk` | not published | **v1.2.1 live** |
| Docker Hub `greenhelix/a2a-gateway` | not published | **v1.2.1 + `latest`** |
| `/.well-known/agent-card.json` | not deployed | **live at api.greenhelix.net** |
| `AGENTS.md` / `SKILL.md` | missing | **present** |
| sandbox.greenhelix.net | not hosted | **live** |
| `integrations/langchain` | missing | **local package (unpublished)** |
| `integrations/crewai` | missing | **local package (unpublished)** |
| Gatekeeper (Z3 formal verification) | N/A | **v1.2.0 released + wired** |
| Tool count | 125 | **141** |

**Implication:** all P0 "publish the binaries" work from v0.5.0 is done.
The remaining work is **registration / submission / documentation
optimisation**, plus a short list of new framework wrappers.

---

## 2. Discovery Protocols & Marketplaces

Autonomous agents find services through one of three discovery surfaces.
We target all three.

### 2.1 Protocol-Level Discovery (what the agent's runtime reads)

| Protocol | Version | Who Reads It | Artefact | Status |
|----------|---------|--------------|----------|--------|
| **Model Context Protocol (MCP)** | 2025-11 | Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot, CrewAI, LangChain MCP adapter, Google ADK, OpenAI Agents SDK MCP support | stdio or HTTP MCP server; `mcp.json` entries | Not yet shipped — **P0** |
| **A2A Protocol** (Google → Linux Foundation) | 0.4 | a2aregistry.org, a2a.ac, Google ADK discovery, Cloudflare A2A directory | `/.well-known/agent-card.json` | **Shipped** |
| **agents.json** (Wild Card) | 0.3 | Wildcard-AI runtime, OpenAI function calling resolvers | `/.well-known/agents.json` (OpenAPI-flavoured) | Not shipped — **P0** |
| **OpenAPI 3.1** | 3.1.0 | Any LLM with function-calling; Auto-GPT, Toolhouse, SuperAGI, Shortwave | `/v1/openapi.json` | **Shipped** (exposed via Swagger) |
| **Agent Commerce Kit (Stripe)** | 0.1 | Stripe-powered agents, "Stripe for agents" runtime | `x-stripe-agent-commerce` OpenAPI extension + `agent-commerce.json` | Not shipped — **P1** |
| **ACP — Agent Connect Protocol** (LangChain) | 0.2 | LangGraph Cloud, LangChain Hub | ACP server descriptor | Not shipped — **P2** |
| **AGNTCY** (Cisco Outshift) | 0.1 | Cisco agents, CoreAI network | AGNTCY skill card | Not shipped — **P3** (wait for traction) |
| **ANP — Agent Network Protocol** (Alibaba / cnACG) | 0.2 | Qwen-Agent, Dify, Chinese market | ANP manifest | Not shipped — **P3** (regional) |

**Bet:** MCP wins the 2026 client-side standard, A2A wins the 2026 server-side
discovery standard, and Agent Commerce Kit becomes the 2027 payments manifest.
We should publish all three. ACP/AGNTCY/ANP are hedge bets — track, do not
invest until one breaks out.

### 2.2 Registry-Level Discovery (where humans and planner-LLMs search)

| Registry | Scale | Submission | Status |
|----------|-------|-----------|--------|
| **Official MCP Registry** (registry.modelcontextprotocol.io) | ~120 canonical | `mcp-publisher publish` after PyPI/npm | **P0** — blocked on MCP server package |
| **mcp.so** | 19K+ listings | GitHub issue | **P0** — submit now with gateway URL + docs |
| **Glama** (glama.ai/mcp/servers) | 17K+ | "Add Server" → quality review | **P0** — README is ready |
| **Smithery.ai** | 7.3K+ | `smithery mcp publish` CLI | **P0** — needs MCP server wrapper |
| **PulseMCP** | 10.9K+ | Web form | **P0** — editorial "Top Picks" worth targeting |
| **awesome-mcp-servers** (modelcontextprotocol/servers) | Curated | GitHub PR | **P1** — high trust signal |
| **a2aregistry.org** | 15+ verified | Register via agent-card.json | **P0** — agent card is live |
| **a2a.ac** | Largest A2A directory | Web form | **P1** |
| **a2a-registry.org** | DNS-verified | TXT record + form | **P1** |
| **Google ADK Hub** | New, low volume | JSON manifest PR | **P1** |
| **Vercel AI SDK Tools Registry** | TypeScript | PR to `vercel/ai` registry | **P1** |
| **LangChain Hub** (smith.langchain.com/hub) | Very high | pip-installable, LangSmith auth | **P1** |
| **LlamaIndex LlamaHub** | Very high | PR to `run-llama/llama_index` | **P2** |
| **HuggingFace Spaces Agents** | Very high | HF Space + `README.md` tags | **P2** |
| **PulseMCP Newsletter** (editorial) | ~12K subs | Pitch email | **P2** |

### 2.3 Developer-Marketplace Discovery (human → agent builders)

These are where engineers building agents go to shop for services:

| Channel | Audience | Mechanism | Priority |
|---------|----------|-----------|----------|
| **Cursor MCP directory** (cursor.com/mcp) | 500K+ IDE users | `mcp.json` in repo + docs | P0 |
| **Claude Desktop** | Anthropic power users | Copy-paste `claude_desktop_config.json` | P0 |
| **Claude Code** | Anthropic devs | `/mcp add` flow + docs page | P0 |
| **Windsurf MCP** | IDE users | Windsurf directory submission | P1 |
| **Zed MCP** | IDE users | Extension manifest | P2 |
| **OpenAI GPT Store / Custom GPTs** | ChatGPT users | GPT with A2A SDK actions | P1 |
| **Hacker News "Show HN"** | Dev-news | One launch post | P0 |
| **Product Hunt** | Dev + maker | One launch post | P1 |
| **dev.to / Medium tutorials** | Search traffic | 3 tutorial posts | P1 |
| **r/LocalLLaMA, r/AI_Agents, r/LLMDevs** | 800K+ combined | Technical posts | P1 |

---

## 3. Infrastructure Integrations (Top 5 — 2026-2027 Horizon)

Framework adoption is lumpy. These are the 5 highest-leverage integrations,
weighted by 2026 download volume, 2027 projected growth, and transaction
conversion rate (i.e., how likely the framework's planner is to actually
*call* a paid tool vs. bounce).

### #1 — **Model Context Protocol (MCP) Server** *(top priority)*

**Why:** MCP is the *lingua franca* for agent tool-calling in 2026. Claude
Desktop, Claude Code, Cursor, Windsurf, OpenAI Agents SDK, Google ADK, CrewAI,
LangChain (`langchain-mcp-adapters`), and LlamaIndex all speak it natively.
One MCP server implementation lights up **10+ client runtimes simultaneously**.

**What to ship:**
- `products/mcp_server/` — a thin wrapper around the gateway that exposes
  all 141 tools via the MCP `tools/list` + `tools/call` methods over
  stdio and streamable HTTP transports.
- PyPI package `a2a-mcp-server` (installs as `a2a-mcp-server` CLI).
- npm package `@greenhelix/mcp-server` (Node entry point).
- Docker image `greenhelix/a2a-mcp-server` (stdio via `docker run -i`).
- Publish to the Official MCP Registry via `mcp-publisher`.
- Submit to mcp.so, Glama, Smithery, PulseMCP.
- Example `claude_desktop_config.json` snippet in README.
- Example `cursor/mcp.json` snippet in README.
- One-click "Install in Claude" deep link (`claude://install-mcp?...`).

**Effort:** ~1 day (the gateway already has a tool registry — wrap it).
**Expected reach:** >80% of all MCP-capable agents.

### #2 — **LangGraph / LangChain Tool Pack**

**Why:** LangChain Python downloads ≈ 50M/month in 2026; LangGraph is the
de-facto durable-agent runtime. A native tool pack gets us into every
LangGraph agent by `pip install a2a-langchain`.

**What to ship:**
- `integrations/langchain/` — **already drafted locally**. Publish to PyPI as
  `a2a-langchain`.
- Add a `LangChainToolPack` class that returns `StructuredTool` instances for
  each billing/payments/marketplace operation.
- Submit a PR to `langchain-community` adding an entry to the Community tools
  index, pointing at our package.
- Submit to LangChain Hub (`smith.langchain.com/hub`) with an
  example LangGraph agent showing "pay another agent for a service".

**Effort:** ~1 day (package exists, needs publishing + PRs).
**Expected reach:** ~40% of Python agent builders.

### #3 — **CrewAI MCP + Native Tool Package**

**Why:** CrewAI is the fastest-growing multi-agent framework (≈5M/mo in 2026).
It supports both native Python tools and MCP tools. Double-dipping is cheap.

**What to ship:**
- `integrations/crewai/` — **already drafted locally**. Publish to PyPI as
  `a2a-crewai`.
- Add a `CrewAIToolset` class returning `@tool`-decorated callables.
- Reference docs showing a multi-agent "buyer crew / seller crew" demo.
- Submit to the CrewAI community tools index.

**Effort:** ~0.5 day.
**Expected reach:** ~15% of multi-agent workflow builders.

### #4 — **Vercel AI SDK Tools Registry Entry**

**Why:** Vercel AI SDK dominates the TypeScript/Next.js agent ecosystem. The
Tools Registry is the canonical discovery surface for `ai@4.x` `tool()` helpers.
A single JSON manifest + a couple of import lines gets us into every Next.js
agent project.

**What to ship:**
- `integrations/vercel-ai/` — a small TS package wrapping `@greenhelix/sdk`
  with `tool()` helpers compatible with Vercel AI SDK v4.
- Publish to npm as `@greenhelix/vercel-ai-tools`.
- Submit PR to `vercel/ai` Tools Registry with manifest entry.

**Effort:** ~0.5 day.
**Expected reach:** ~30% of TypeScript agent builders.

### #5 — **Cursor / Claude Code / Windsurf IDE Integrations**

**Why:** IDE-embedded agents are where developers actually *try* new tools.
Getting a one-click install in Cursor means every developer who types
"help me add payments to my agent" into Cursor gets us as the top suggestion.

**What to ship:**
- `docs/integrations/cursor.md` — copy-paste `mcp.json` snippet using our MCP
  server.
- `docs/integrations/claude-code.md` — `/mcp add` flow.
- `docs/integrations/claude-desktop.md` — `claude_desktop_config.json` entry.
- `docs/integrations/windsurf.md` — Windsurf settings entry.
- Submit to Cursor's MCP directory (form on cursor.com/mcp).

**Effort:** ~0.25 day (docs only, depends on #1 being shipped).
**Expected reach:** ~500K IDE users collectively.

### Framework Deprioritisation

We deliberately skip these in 2026:
- **AutoGen / AG2** — Microsoft merged the ecosystem into "Agent Framework".
  Low current volume, high churn risk.
- **AutoGPT** — stagnant, low transaction conversion.
- **SuperAGI** — niche, declining.
- **BabyAGI / descendants** — hobby-scale.
- **Aider** — excellent tool but does not consume external tool APIs; wait.

---

## 4. Agent-SEO Strategy

Planner LLMs (GPT-4.1, Claude Opus 4.6, Gemini 2.5) choose which service to
call by reading descriptions and metadata. "Agent-SEO" is the discipline of
shaping those descriptions so that planners pick us over competitors.

### 4.1 The Three-Layer Ranking Model

Agent planners typically rank candidate tools by a weighted score over:

1. **Semantic match** — does the tool's `description` match the task? This
   dominates — get it right or you don't enter the candidate set.
2. **Trust signals** — provider reputation, verified identity, historical
   success rate. Covered by our `reputation` tools + `/well-known/agent-card`.
3. **Operational cost** — price, latency, rate limits, auth complexity.

Our content strategy must optimise all three.

### 4.2 Concrete `.well-known/` Artefacts

Expand beyond `agent-card.json`. Publish:

| Path | Purpose | Format |
|------|---------|--------|
| `/.well-known/agent-card.json` | A2A Protocol card | **live** |
| `/.well-known/agents.json` | Wildcard / agents.json OpenAPI-flavoured | JSON — **ship** |
| `/.well-known/ai-plugin.json` | OpenAI plugin manifest (legacy but still read by ChatGPT actions, Poe, Toolhouse) | JSON — **ship** |
| `/.well-known/mcp.json` | Claude Desktop / Cursor discovery | JSON — **ship** |
| `/.well-known/agent-commerce.json` | Stripe Agent Commerce Kit manifest | JSON — **ship** |
| `/.well-known/llms.txt` | llms.txt standard for LLM-readable site map | Markdown — **ship** |
| `/.well-known/llms-full.txt` | Full knowledge dump for LLM consumption | Markdown — **ship** |
| `/.well-known/security.txt` | Security contact (already standard) | Text — check |
| `/robots.txt` | Allow all agent user-agents explicitly (GPTBot, ClaudeBot, Google-Extended, PerplexityBot, Applebot-Extended, Bytespider) | Text — ship |

**Key detail:** publish both `llms.txt` (short, curated) and `llms-full.txt`
(complete API reference). Planner LLMs that support RAG-augmented tool
resolution will ingest `llms-full.txt` during planning.

### 4.3 Tool Description Optimisation

Every tool in `pricing.json` has a `description`. These are the text the
planner reads. Apply the following template:

> `<verb> <object> for <use case>. Accepts <params>. Returns <output>. Ideal when <trigger>. Price: <cost>.`

**Before:**
```
create_intent — Create a payment intent
```

**After:**
```
create_intent — Authorise a payment of up to $1M from one agent to another
without capturing funds. Use this when an agent needs to commit budget for a
purchase it has not yet received. Returns an intent_id that can later be
captured, cancelled, or refunded. Cost: 0.01 credits (~$0.0001). SLA: p99
<50ms.
```

**Why this works:** the planner's embedding model scores semantic similarity
against the user's task. Adding "authorise", "commit budget", "without
capturing" makes us match queries like *"hold some money"*, *"reserve funds"*,
*"commit without paying yet"* — which a terse description would miss.

### 4.4 Pricing Machine-Readability

Publish pricing at `/.well-known/agent-pricing.json` in a format that
matches the Stripe Agent Commerce Kit pricing schema:

```json
{
  "currency": "USD",
  "models": {
    "credits": {"rate": 0.01, "unit": "call"},
    "percentage_fee": {"basis_points": 100, "min": 0.01, "max": 5.00}
  },
  "free_tier": {"credits": 500, "rate_limit": "100/hr"},
  "tiers": [...]
}
```

This is the machine-readable twin of `/v1/pricing`. Planner LLMs that
consider cost as a ranking factor can parse this directly.

### 4.5 Trust Signals

Three concrete trust signals a planner LLM will look for:

1. **Verifiable reputation** — expose trust scores at `/v1/trust/score/<agent_id>`
   with a signed response. Reference this in the agent card as
   `capabilities.reputation.endpoint`.
2. **Cryptographic identity** — we already ship Ed25519 agent identity.
   Add the public key to `agent-card.json → provider.public_key`.
3. **Formal verification** — Gatekeeper (Z3) is a unique moat. Surface it
   in the agent card: `capabilities.formal_verification: true` with a link
   to `/v1/gatekeeper/docs`. **No competing A2A platform has this.**

### 4.6 Name-Anchoring

Planners tend to rank tools whose *name* matches the task. Our PyPI and
npm package names should contain high-search-volume tokens:

- `a2a-greenhelix-sdk` ✅ good (contains "a2a")
- `@greenhelix/sdk` ⚠️ missing "a2a" and "mcp"
- Future: publish alias `@greenhelix/a2a-mcp` and `greenhelix-agent-payments`
  (squat variants before competitors do)

---

## 5. ROI Ranking Table

Rows are ordered top-to-bottom by **Overall ROI**. Effort is in engineer-days;
Reach is a rough 2026-Q3 estimate of monthly agent-request volume we could
plausibly capture; Conversion is the likelihood that an agent reaching us
actually completes a paid transaction.

| # | Channel / Integration | Reach (mo) | Effort (d) | Conversion | Overall ROI |
|---|----------------------|------------|-----------|------------|-------------|
| 1 | **MCP Server + Official Registry** | ~500K | 1.0 | High | **High** |
| 2 | **mcp.so + Glama + Smithery + PulseMCP submissions** | ~200K | 0.5 | High | **High** |
| 3 | **`.well-known/` artefact bundle** (agents.json, ai-plugin.json, llms.txt, mcp.json, agent-commerce.json) | ~150K | 0.5 | High | **High** |
| 4 | **Tool description optimisation** in `pricing.json` | ~300K (boost) | 0.5 | High | **High** |
| 5 | **LangGraph / LangChain Tool Pack** on PyPI | ~200K | 1.0 | High | **High** |
| 6 | **Cursor / Claude Desktop / Claude Code docs** | ~500K | 0.25 | Medium | **High** |
| 7 | **CrewAI Toolset** on PyPI | ~80K | 0.5 | High | **High** |
| 8 | **Vercel AI SDK Tools Registry entry** | ~100K | 0.5 | Medium | **High** |
| 9 | **awesome-mcp-servers PR** | ~80K | 0.1 | Medium | **High** |
| 10 | **a2aregistry.org + a2a.ac registration** | ~50K | 0.1 | Medium | **High** |
| 11 | **GitHub repo topics + README quickstart + badges** | ~40K | 0.25 | Low | Medium |
| 12 | **Hacker News "Show HN" launch** | spike ~30K | 0.5 | Low | Medium |
| 13 | **LlamaIndex LlamaHub integration** | ~50K | 1.0 | Medium | Medium |
| 14 | **dev.to tutorial series (3 posts)** | ~20K | 1.5 | Medium | Medium |
| 15 | **Product Hunt launch** | spike ~15K | 0.5 | Low | Medium |
| 16 | **OpenAI Custom GPT + Actions** | ~50K | 1.0 | Low | Medium |
| 17 | **AI Agent Store + AI Agents Directory listings** | ~10K | 0.1 | Low | Medium |
| 18 | **r/LocalLLaMA / r/AI_Agents / r/LLMDevs posts** | ~20K | 0.25 | Low | Medium |
| 19 | **Discord engagement (LangChain / CrewAI / Glama)** | ~5K | ongoing | Medium | Low |
| 20 | **Google ADK Hub manifest** | ~10K | 0.5 | Medium | Low |
| 21 | **HuggingFace Space + tags** | ~15K | 0.5 | Low | Low |
| 22 | **ACP (Agent Connect Protocol) manifest** | ~5K | 0.5 | Low | Low |
| 23 | **AGNTCY skill card** | ~2K | 0.25 | Low | Low |
| 24 | **ANP manifest (Alibaba)** | ~10K regional | 0.5 | Low | Low |
| 25 | **Conference sponsorships (AI Engineer Summit / NeurIPS)** | ~3K | 0 eng / $5-10K | Low | Low |

**Interpretation:** rows 1-10 are all "High ROI" and total ~4.5 engineer-days
of work. That is the entire distribution budget for the next sprint. Rows
11-18 are Month 2. Rows 19-25 are hedges — do not invest until market signal
justifies.

---

## 6. Detailed Action Plan — Agent (Engineering)

These tasks are committable code changes. They are written so an agent can
pick them up from `tasks/backlog/distribution-execution-queue.md` and
execute autonomously. Ordering matches ROI rank.

### Sprint 1 (4.5 engineer-days — do this first)

#### A1. Build & publish MCP server — 1 day
- Create `products/mcp_server/` package with:
  - `server.py` exposing `tools/list` and `tools/call` over stdio and
    streamable HTTP (`mcp[server]>=0.9`)
  - Tool enumeration: pull from gateway's existing tool registry at startup
  - Auth passthrough: accept `A2A_API_KEY` env var, forward as `Authorization`
    header to the gateway
  - CLI entry `a2a-mcp-server` (stdio by default, `--http` for HTTP)
- Add `pyproject.toml` → publish to PyPI as `a2a-mcp-server`
- Add `sdk-ts/mcp-server/` with Node wrapper → publish as
  `@greenhelix/mcp-server`
- Build + push Docker image `greenhelix/a2a-mcp-server`
- Run `mcp-publisher publish` with `io.github.mirni/a2a-gateway` namespace
- Tests: contract test against MCP `tools/list` schema

#### A2. Submit to MCP registries (batch) — 0.5 day
- mcp.so: open a GitHub issue on `chatmcp/mcp-directory` with our metadata
- Glama: "Add Server" form at glama.ai/mcp/servers
- Smithery: `npx -y @smithery/cli publish` with `smithery.yaml` in repo root
- PulseMCP: web form at pulsemcp.com/submit
- Keep a table of submission state in `reports/distribution-tracker.md`

#### A3. Ship the `.well-known/` artefact bundle — 0.5 day
- Add FastAPI routes in `gateway/src/routes/well_known.py` serving:
  - `/.well-known/agents.json` (Wildcard agents.json schema)
  - `/.well-known/ai-plugin.json` (OpenAI plugin manifest)
  - `/.well-known/mcp.json` (Claude Desktop / Cursor discovery)
  - `/.well-known/agent-commerce.json` (Stripe Agent Commerce Kit)
  - `/.well-known/llms.txt` (short curated)
  - `/.well-known/llms-full.txt` (full API knowledge dump — generated from
    `/v1/openapi.json`)
  - `/.well-known/agent-pricing.json` (machine-readable pricing)
- Update `robots.txt` to explicitly allow GPTBot, ClaudeBot, Google-Extended,
  PerplexityBot, Applebot-Extended, Bytespider
- Tests: contract test each endpoint against its schema

#### A4. Tool description optimisation — 0.5 day
- Rewrite all 141 tool `description` fields in `pricing.json` and
  `products/*/src/tools/*.py` using the verb-object-use case template from
  §4.3 above
- Add `use_cases` and `ideal_when` keys to each tool definition
- Regenerate OpenAPI spec; verify Swagger UI renders
- Snapshot test: tool descriptions contain at least 20 tokens + price

#### A5. Publish LangChain / LangGraph tool pack — 1 day
- `integrations/langchain/` already exists locally
- Bump version to `0.2.0`, add `LangChainToolPack` class returning
  `StructuredTool` instances pulled from the gateway's tool registry
- Add a LangGraph example notebook under
  `integrations/langchain/examples/langgraph_agent.ipynb`
- Publish to PyPI via existing `scripts/publish_package.sh`
- Submit PR to `langchain-ai/langchain` adding an entry to
  `libs/community/langchain_community/tools/README.md`

#### A6. Publish CrewAI toolset — 0.5 day
- `integrations/crewai/` already exists locally
- Bump version to `0.2.0`, add `CrewAIToolset` class
- Add a two-crew buyer/seller example under
  `integrations/crewai/examples/marketplace_crew.py`
- Publish to PyPI
- Submit to the CrewAI community tools index

#### A7. Cursor / Claude / Windsurf docs — 0.25 day
- Create `docs/integrations/`:
  - `cursor.md` with copy-paste `mcp.json`
  - `claude-desktop.md` with `claude_desktop_config.json`
  - `claude-code.md` with `/mcp add` flow
  - `windsurf.md` with settings snippet
- Add "Install in <IDE>" buttons to `website/index.html`
- Cross-link from README

### Sprint 2 (Month 2)

#### A8. Vercel AI SDK tools package — 0.5 day
- Create `integrations/vercel-ai/` with `@greenhelix/vercel-ai-tools`
- Export `ai` SDK `tool()` helpers for each gateway endpoint
- Publish to npm
- Submit PR to `vercel/ai` Tools Registry

#### A9. awesome-mcp-servers PR — 0.1 day
- Fork `modelcontextprotocol/servers`, add entry under "Commerce & Payments"
- Submit PR with the one-liner

#### A10. a2aregistry.org + a2a.ac registration — 0.1 day
- Submit agent card URL via a2aregistry.org form
- Submit to a2a.ac

#### A11. README + repo topics + badges — 0.25 day
- Add badges: PyPI version, npm version, Docker pulls, MCP registry
- Add "Install in Claude Desktop" button and MCP one-liner
- Add 30-second quickstart (single pip install → working `pay_agent` call)
- Update GitHub repo topics (needs human action — see §7)

#### A12. LlamaIndex LlamaHub integration — 1 day
- Create `integrations/llamaindex/` with `A2AToolSpec`
- Submit PR to `run-llama/llama_index` under
  `llama-index-integrations/tools/llama-index-tools-a2a`

#### A13. dev.to tutorial series — 1.5 days
- Post 1: "Agent Payments in 5 Minutes — the MCP Way"
- Post 2: "Building a Marketplace Crew with CrewAI + A2A Commerce"
- Post 3: "Escrow for AI Contracts — Performance-Gated Payments"

#### A14. Distribution tracker dashboard — 0.25 day
- `reports/distribution-tracker.md` — table of every channel, submission
  date, status, metric URL
- Optional: `scripts/collect_distribution_metrics.py` pulling download
  counts from pypistats, npmjs, docker hub, mcp.so

### Sprint 3 (Month 3 — hedge bets)

- A15. Google ADK Hub manifest — 0.5 day
- A16. HuggingFace Space + tags — 0.5 day
- A17. Stripe Agent Commerce Kit compliance audit — 0.5 day
- A18. OpenAI Custom GPT with A2A actions — 1 day

---

## 7. Detailed Action Plan — Human

Items requiring a human account, credentials, or decision. Listed in order
of urgency.

### H1. Accounts & Credentials (do these first)

| # | Action | Why | Cost | Time |
|---|--------|-----|------|------|
| H1.1 | Register `mcp-publisher` account (GitHub OAuth) | Required for Official MCP Registry publish | Free | 5 min |
| H1.2 | Create `smithery.ai` account (GitHub OAuth) | Required for `smithery mcp publish` | Free | 5 min |
| H1.3 | Create `glama.ai` account | Required for "Add Server" form | Free | 5 min |
| H1.4 | Create `pulsemcp.com` account | Required for web form | Free | 5 min |
| H1.5 | Create `langchain` Discord account | Community engagement (not drive-by) | Free | 5 min |
| H1.6 | Create `crewai` Discord account | Community engagement | Free | 5 min |
| H1.7 | Verify `greenhelix` org on npm (domain verification) | Lets us publish `@greenhelix/*` scoped packages reliably | Free | 10 min |
| H1.8 | Add GitHub repo topics | Agent A2 can't do this via CLI | Free | 2 min |
| H1.9 | Create Cursor MCP directory submission (form) | Required for directory inclusion | Free | 10 min |
| H1.10 | Create `a2aregistry.org` account | Required to submit | Free | 5 min |
| H1.11 | Create Hacker News account with karma ≥ 1 (if needed) | Launch post | Free | — |
| H1.12 | Create Product Hunt account + hunter relationship | Launch requires a hunter ideally | Free | 30 min |

**GitHub repo topics to add** (Settings → Topics):
```
ai-agents, mcp, mcp-server, a2a, agent-commerce, agent-payments,
agent-to-agent, escrow, trust-scoring, marketplace, stripe, fastapi,
python, typescript, formal-verification, z3, developer-tools
```

### H2. Decisions Needed From Human

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| H2.1 | npm scope: keep `@greenhelix` or add `@a2a` alias? | (a) `@greenhelix` only (b) add `@a2a` alias | **(b)** — "a2a" is high-search-volume |
| H2.2 | PyPI name strategy: single `a2a-greenhelix-sdk` or split into `a2a-sdk` + meta package? | (a) status quo (b) alias `a2a-sdk` as meta | **(a)** — avoid name collision with existing `a2a` PyPI squatters |
| H2.3 | MCP server auth default | (a) Read-only (no key) (b) Require API key | **(b)** — ties usage to billing |
| H2.4 | Hacker News launch angle | (a) "Stripe for agents" (b) "Formal verification for agent payments" (c) "MCP server for 141 commerce tools" | **(c)** — technical audience, least marketing-y |
| H2.5 | Product Hunt category | (a) AI Agents (b) Developer Tools (c) APIs | **(a)** — highest volume for our audience |
| H2.6 | Conference budget for AI Engineer Summit / NeurIPS | (a) Skip (b) $5K (c) $10K | **(a)** until MRR > $5K |
| H2.7 | Which framework gets "first-party" branding? (we can only promise SLA on one) | (a) LangChain (b) LangGraph (c) CrewAI (d) MCP (framework-agnostic) | **(d)** — MCP is framework-agnostic, hedge bet |
| H2.8 | Publish `llms-full.txt` with full API? | (a) Yes (b) Yes but gated (c) No | **(a)** — public API is already public |
| H2.9 | Enable `@greenhelix/a2a-mcp` npm alias? | (a) Yes (b) No | **(a)** — name squat insurance |
| H2.10 | Distribution tracker — private or public dashboard? | (a) Private (b) Public | **(a)** — signals traction honestly |

### H3. Human-Only Publicity

| # | Action | When | Prep |
|---|--------|------|------|
| H3.1 | Submit Hacker News "Show HN" | After A1-A7 done | Draft title: *"Show HN: Open-source commerce gateway with MCP server for AI agents (Stripe, escrow, trust)"* |
| H3.2 | Submit Product Hunt launch | 2 weeks after HN | Find a hunter with ≥5K followers |
| H3.3 | Engage LangChain Discord | Ongoing | Answer 3+ questions/week before any self-promotion |
| H3.4 | Engage CrewAI Discord | Ongoing | Same rule |
| H3.5 | Engage MCP Discord (`discord.gg/modelcontextprotocol`) | Ongoing | Share demo video when MCP server ships |
| H3.6 | Reddit posts — r/LocalLLaMA, r/AI_Agents, r/LLMDevs | After MCP server ships | Technical, not promotional. Read rules. |
| H3.7 | Podcast outreach — Latent Space, TWIML, MLOps Community | Month 2+ | Have a 5-min demo ready |

---

## 8. Metrics & Kill Criteria

### Leading indicators (weekly review)

| Metric | Week 2 | Week 6 | Week 12 |
|--------|--------|--------|---------|
| MCP server installs (mcp-publisher stats) | 50 | 500 | 2,000 |
| PyPI weekly downloads (`a2a-greenhelix-sdk`) | 100 | 1,000 | 5,000 |
| PyPI weekly downloads (`a2a-langchain` + `a2a-crewai` + `a2a-mcp-server`) | 50 | 500 | 3,000 |
| npm weekly downloads (`@greenhelix/sdk` + `@greenhelix/mcp-server`) | 50 | 500 | 2,000 |
| Docker Hub pulls (`greenhelix/a2a-gateway`) | 100 | 500 | 2,000 |
| mcp.so page views | 500 | 3,000 | 10,000 |
| Glama quality score | listed | listed | top 200 |
| GitHub stars | 25 | 150 | 500 |
| Registered agent wallets (with ≥1 call) | 25 | 100 | 300 |

### Lagging indicators (monthly)

| Metric | Month 1 | Month 3 | Month 6 |
|--------|---------|---------|---------|
| Agents making paid calls | 10 | 75 | 250 |
| MRR | $50 | $1,500 | $8,000 |
| Unique planner frameworks observed in User-Agent | 3 | 8 | 15 |

### Kill criteria

Cut investment in any Sprint-2 or Sprint-3 integration whose 6-week install
count is < 50. Reallocate effort to whatever is actually producing traffic.

---

## 9. Competitive Moat (keep this in mind)

Three compounding advantages that we should surface in every distribution
channel:

1. **Formal verification of agent properties (Z3)** — unique. No competitor
   ships this. Surface in every MCP server description, tool docstring, and
   launch post.
2. **Cryptographic identity + reputation** — Ed25519 + trust scores +
   time-series metrics. Competitors fake it; we can prove it.
3. **Dual-protocol discoverability** — we sit on both MCP *and* A2A Protocol.
   Most competitors pick one.

Every `description`, every README, every registry listing should repeat the
same three-word hook: *"Verifiable agent commerce."*

---

## Appendix A: Distribution Tracker Template

A running spreadsheet of every submission. Should live at
`reports/distribution-tracker.md` and be updated every Friday.

| Channel | Submitted | Approved | Listed URL | Weekly Views | Weekly Installs | Notes |
|---------|-----------|----------|------------|--------------|-----------------|-------|
| mcp.so | | | | | | |
| Glama | | | | | | |
| Smithery | | | | | | |
| PulseMCP | | | | | | |
| Official MCP Registry | | | | | | |
| awesome-mcp-servers | | | | | | |
| a2aregistry.org | | | | | | |
| Cursor MCP directory | | | | | | |
| LangChain Community PR | | | | | | |
| CrewAI tools index | | | | | | |
| Vercel AI SDK registry | | | | | | |
| LlamaHub | | | | | | |
| AI Agent Store | | | | | | |
| AI Agents Directory | | | | | | |
| HN Show HN | | | | | | |
| Product Hunt | | | | | | |
| dev.to post 1 | | | | | | |
| dev.to post 2 | | | | | | |
| dev.to post 3 | | | | | | |

## Appendix B: Protocol Bet Heat-Map (2026-2027)

| Protocol | 2026 Q2 | 2026 Q4 | 2027 Q2 | Our Bet |
|----------|---------|---------|---------|---------|
| MCP | **Hot** | **Hot** | **Hot** | Ship first |
| A2A Protocol | Warm | **Hot** | **Hot** | Shipped |
| Agent Commerce Kit (Stripe) | Cold | Warm | **Hot** | Ship P1 |
| agents.json (Wildcard) | Warm | Warm | Warm | Ship P1 |
| OpenAPI 3.1 + function calling | **Hot** | Warm | Warm | Shipped |
| ACP (LangChain) | Cold | Warm | ? | Watch |
| AGNTCY (Cisco) | Cold | Cold | ? | Watch |
| ANP (Alibaba / cnACG) | Cold | Warm (CN) | Warm (CN) | Watch |
| AutoGen / AG2 | Declining | Cold | Cold | **Skip** |

---

*End of document. Ready for human review. Execute Sprint 1 items (A1-A7) as
the next work unit — they share a common feature branch and can land in a
single PR.*
