# Distribution Execution Queue — ROI-Sorted

**Source:** `docs/infra/AGENT_DISTRIBUTION_STRATEGY_2026-04.md`
**Created:** 2026-04-10
**Owner:** Engineering agent
**Linked strategy doc:** `docs/infra/AGENT_DISTRIBUTION_STRATEGY_2026-04.md`

Tasks are **strictly ordered by ROI**. Pick from the top. Each task is
self-contained — one task → one feature branch → one PR.

Convention: `[ ]` pending, `[~]` in progress, `[x]` done.

---

## Sprint 1 — High ROI (~4.5 engineer-days total)

### [ ] A1. Build & publish the MCP server
**Reach:** ~500K agents/mo · **Effort:** 1.0d · **ROI:** High

**Why:** MCP is the lingua franca for agent tool-calling. One server lights
up Claude Desktop, Claude Code, Cursor, Windsurf, OpenAI Agents SDK, Google
ADK, CrewAI, LangChain MCP adapter, and LlamaIndex simultaneously.

**Deliverables:**
- New package `products/mcp_server/` with:
  - `server.py` exposing MCP `tools/list` + `tools/call` over stdio and
    streamable HTTP using `mcp>=0.9`
  - Dynamically enumerate tools from gateway's tool registry at startup
  - Forward `A2A_API_KEY` env var as `Authorization: Bearer` header
  - CLI entry `a2a-mcp-server` (stdio default, `--http <port>` for HTTP)
  - Pydantic models mirroring the gateway request/response shapes
- `pyproject.toml` → publish to PyPI as `a2a-mcp-server`
- `sdk-ts/mcp-server/` Node wrapper → publish as `@greenhelix/mcp-server`
- Dockerfile → publish `greenhelix/a2a-mcp-server:latest` and `:1.2.1`
- TDD: contract test against MCP `tools/list` schema, `tools/call` round trip
- Run `mcp-publisher publish` under namespace `io.github.mirni/a2a-gateway`
- Update `.github/workflows/release.yml` to auto-publish on tag
- Add example `claude_desktop_config.json` and `cursor/mcp.json` snippets to
  the new package's README

**Acceptance:**
- `pip install a2a-mcp-server && A2A_API_KEY=test a2a-mcp-server --help` works
- `npx -y @greenhelix/mcp-server` works
- Integration test invokes `tools/call` → gateway → live response
- Package listed on registry.modelcontextprotocol.io

---

### [ ] A2. Submit to MCP registries (batch)
**Reach:** ~200K agents/mo · **Effort:** 0.5d · **ROI:** High

**Depends on:** A1 complete (need packages live)

**Deliverables:**
- Submit to **mcp.so** via GitHub issue on `chatmcp/mcp-directory`
- Submit to **Glama** via "Add Server" form at glama.ai/mcp/servers
- Add `smithery.yaml` to repo root + run `npx -y @smithery/cli publish`
- Submit to **PulseMCP** via web form at pulsemcp.com/submit
- Create `reports/distribution-tracker.md` with table of every submission
  and its URL, submit date, status

**Acceptance:**
- All 4 directories have a pending or live listing
- Tracker file committed

---

### [ ] A3. Ship `.well-known/` artefact bundle
**Reach:** ~150K agents/mo · **Effort:** 0.5d · **ROI:** High

**Deliverables:**
- New file `gateway/src/routes/well_known.py` serving:
  - `/.well-known/agents.json` — Wildcard agents.json OpenAPI-flavoured
  - `/.well-known/ai-plugin.json` — OpenAI plugin manifest (legacy but read
    by ChatGPT Actions, Poe, Toolhouse)
  - `/.well-known/mcp.json` — Cursor/Claude Desktop discovery
  - `/.well-known/agent-commerce.json` — Stripe Agent Commerce Kit manifest
  - `/.well-known/llms.txt` — short curated LLM site map
  - `/.well-known/llms-full.txt` — full API knowledge dump (auto-generated
    from `/v1/openapi.json` via a build script)
  - `/.well-known/agent-pricing.json` — machine-readable pricing
- Update `website/robots.txt` (or add one) to explicitly allow: `GPTBot`,
  `ClaudeBot`, `Google-Extended`, `PerplexityBot`, `Applebot-Extended`,
  `Bytespider`, `CCBot`
- TDD: contract test each endpoint against its schema

**Acceptance:**
- `curl https://api.greenhelix.net/.well-known/agents.json` returns valid JSON
- All 7 endpoints return 200 with correct `Content-Type`
- `robots.txt` served at both the website and the API root

---

### [ ] A4. Tool description optimisation (Agent-SEO)
**Reach:** ~300K boost · **Effort:** 0.5d · **ROI:** High

**Deliverables:**
- Audit all 141 tool `description` fields across `pricing.json` and
  `products/*/src/tools/*.py`
- Rewrite using the template:
  `<verb> <object> for <use case>. Accepts <params>. Returns <output>.
   Ideal when <trigger>. Price: <cost>.`
- Add `use_cases: [str]` and `ideal_when: [str]` keys to each tool definition
- Regenerate OpenAPI spec, verify Swagger UI renders
- Snapshot test: all descriptions ≥ 20 tokens, include price, include at
  least one "ideal when" trigger

**Acceptance:**
- All 141 tools updated
- Tests green
- No regression in `scripts/update_website_stats.py --check`

---

### [ ] A5. Publish LangChain / LangGraph tool pack
**Reach:** ~200K agents/mo · **Effort:** 1.0d · **ROI:** High

**Deliverables:**
- `integrations/langchain/` already exists — bump to `0.2.0`
- Add `LangChainToolPack` class returning `StructuredTool` instances pulled
  from gateway's tool registry at import time
- LangGraph example at `integrations/langchain/examples/langgraph_agent.py`
  showing "buyer agent pays seller agent" flow
- Add 15+ unit tests (TDD) covering tool pack construction, arg schema,
  auth header forwarding, error mapping
- Publish to PyPI as `a2a-langchain` via `scripts/publish_package.sh`
- Submit PR to `langchain-ai/langchain` adding an entry to
  `libs/community/langchain_community/tools/README.md`

**Acceptance:**
- `pip install a2a-langchain` works from a clean venv
- LangGraph example runs end-to-end against sandbox
- LangChain PR open

---

### [ ] A6. Publish CrewAI toolset
**Reach:** ~80K agents/mo · **Effort:** 0.5d · **ROI:** High

**Deliverables:**
- `integrations/crewai/` already exists — bump to `0.2.0`
- Add `CrewAIToolset` class
- Two-crew buyer/seller example at
  `integrations/crewai/examples/marketplace_crew.py`
- Publish to PyPI as `a2a-crewai`
- Submit entry to CrewAI community tools index

**Acceptance:**
- `pip install a2a-crewai` works
- Example runs end-to-end
- Community tools index entry submitted

---

### [ ] A7. Cursor / Claude Desktop / Claude Code / Windsurf docs
**Reach:** ~500K IDE users · **Effort:** 0.25d · **ROI:** High

**Depends on:** A1 complete

**Deliverables:**
- Create `docs/integrations/`:
  - `cursor.md` — copy-paste `mcp.json`
  - `claude-desktop.md` — `claude_desktop_config.json` entry
  - `claude-code.md` — `/mcp add` flow
  - `windsurf.md` — settings snippet
  - `zed.md` — extension manifest
- Add "Install in Claude Desktop" button and MCP one-liner to
  `website/index.html`
- Cross-link from `README.md`

**Acceptance:**
- All 5 docs land
- "Install in Claude Desktop" deep-link button works on the website

---

## Sprint 2 — Medium ROI (Month 2)

### [ ] A8. Vercel AI SDK tools package (~0.5d, Medium ROI)
- `integrations/vercel-ai/` new TS package
- Export `ai@4` `tool()` helpers for each gateway endpoint
- Publish to npm as `@greenhelix/vercel-ai-tools`
- Submit PR to `vercel/ai` Tools Registry

### [ ] A9. awesome-mcp-servers PR (~0.1d, High ROI)
- Fork `modelcontextprotocol/servers`
- Add entry under "Commerce & Payments"
- Submit PR

### [ ] A10. a2aregistry.org + a2a.ac registration (~0.1d, High ROI)
- Submit agent card URL via a2aregistry.org form
- Submit to a2a.ac
- Update `docs/infra/DISTRIBUTION.md` status

### [ ] A11. README + repo topics + badges (~0.25d, Medium ROI)
- Add badges: PyPI version, npm version, Docker pulls, MCP registry stars
- Add "Install in Claude Desktop" button
- Add 30-second quickstart (single `pip install` → working `pay_agent` call)
- (Human action required to add GitHub repo topics — see H1.8)

### [ ] A12. LlamaIndex LlamaHub integration (~1.0d, Medium ROI)
- Create `integrations/llamaindex/` with `A2AToolSpec`
- Tests + example
- Submit PR to `run-llama/llama_index` under
  `llama-index-integrations/tools/llama-index-tools-a2a`

### [ ] A13. dev.to tutorial series (~1.5d, Medium ROI)
- Post 1: "Agent Payments in 5 Minutes — the MCP Way"
- Post 2: "Building a Marketplace Crew with CrewAI + A2A Commerce"
- Post 3: "Escrow for AI Contracts — Performance-Gated Payments"
- Drafts into `docs/blog/`

### [ ] A14. Distribution tracker dashboard (~0.25d, Medium ROI)
- `reports/distribution-tracker.md` with per-channel state
- Optional: `scripts/collect_distribution_metrics.py` pulling download
  counts from pypistats, npmjs, Docker Hub, mcp.so

---

## Sprint 3 — Hedge Bets (Month 3+)

Only start these if Sprint 1 delivered ≥50 installs on at least one channel.

### [ ] A15. Google ADK Hub manifest (~0.5d, Low ROI)
### [ ] A16. HuggingFace Space + tags (~0.5d, Low ROI)
### [ ] A17. Stripe Agent Commerce Kit compliance audit (~0.5d, Medium ROI)
### [ ] A18. OpenAI Custom GPT with A2A actions (~1.0d, Medium ROI)
### [ ] A19. ACP (Agent Connect Protocol) manifest (~0.5d, Low ROI)
### [ ] A20. AGNTCY skill card (~0.25d, Low ROI)
### [ ] A21. ANP (Alibaba) manifest (~0.5d, Low ROI — regional)

---

## Kill Criteria

Cut any Sprint-2 or Sprint-3 integration whose 6-week install count is
< 50. Reallocate effort to whatever is actually producing traffic.

Track results in `reports/distribution-tracker.md` weekly.
