# Distribution Action Plan: A2A Commerce Platform

**Date:** 2026-04-02
**Status:** Draft for human review
**Source:** `tasks/active/distribution-todo.md` + `docs/infra/DISTRIBUTION.md` review

---

## 1. State Assessment (April 2026)

### Product Readiness (Verified)

| Capability | Status | Notes |
|-----------|--------|-------|
| Gateway (128 tools, 15 services) | Ready | Production at api.greenhelix.net |
| Python SDK | 40% ready for PyPI | Missing README, author, classifiers |
| TypeScript SDK | 65% ready for npm | Missing README, author, repo URL |
| MCP Server (3 connectors) | Production-ready | Stripe, GitHub, Postgres via mcp_proxy.py |
| Sandbox | Live | sandbox.greenhelix.net |
| Website docs | Complete | docs.html with full developer guide |
| Stripe Checkout | Live | /v1/checkout + webhook |
| CI/CD | Complete | Release script, staging, production |
| RESTful API | Complete | 148 endpoints + 128 tools |
| /.well-known/agent-card.json | NOT IMPLEMENTED | Blocks A2A protocol discovery |
| SKILL.md | NOT CREATED | Blocks skills.sh distribution |
| AGENTS.md | NOT CREATED | Blocks coding agent adoption |
| SDK READMEs | NOT CREATED | Blocks PyPI/npm discoverability |

### DISTRIBUTION.md Gap Analysis

Items from the existing P0 list and their current status:

| # | P0 Item | Status | Notes |
|---|---------|--------|-------|
| 1 | Publish a2a-sdk to PyPI | **Blocked** | pyproject.toml missing author, classifiers, README |
| 2 | Publish @a2a/sdk to npm | **Blocked** | Missing README, publishConfig, repo URL |
| 3 | Publish Docker image | **Blocked** | Dockerfile fixed (reputation removed), needs registry push |
| 4 | Add GitHub topics | **Not done** | Human action (Settings > Topics) |
| 5-9 | Submit to MCP registries | **Blocked** | Packages must be published first |
| 10 | Host sandbox | **Done** | sandbox.greenhelix.net live |
| 11 | Add developer docs to website | **Done** | website/docs.html exists |

### Landscape Changes Since March 2026

1. **AGENTS.md** adopted by 60,000+ repos (OpenAI, Apache). Under Linux Foundation governance. **Must add.**
2. **skills.sh** now supports 41+ agents, 26K+ installs for top skills. **High priority.**
3. **A2A Protocol** now under Linux Foundation with 150+ orgs. Spec at v0.3 with gRPC. **Growing fast.**
4. **AG2 (AutoGen)** is effectively dead — Microsoft merged into unified Agent Framework. **Remove from priorities.**
5. **Official MCP Registry** stricter verification; namespace-based (io.github.mirni/*).
6. **MCP Server Cards** (.well-known for MCP) on roadmap for Q4 2026. **Get ahead of it.**

---

## 2. Discovery Protocols & Marketplaces

### Where Agents "Look" for Services

| Channel | How Agents Discover | Reach (est.) | Our Status |
|---------|-------------------|-------------|------------|
| **MCP Registries** | mcp_publisher CLI, registry API | 97M SDK downloads/mo | Not listed |
| **A2A Agent Cards** | /.well-known/agent-card.json | 150+ orgs, enterprise | Not implemented |
| **skills.sh** | `npx skills add` | 41+ agents supported | Not listed |
| **LangChain Hub** | pip install, Python import | 47M downloads/mo | No integration |
| **PyPI/npm** | pip install / npm install | Universal | Not published |
| **GitHub** | Repo search, topics, stars | Massive | Topics missing |
| **OpenAPI/Swagger** | /docs, /v1/openapi.json | Developer-first | Done |
| **AGENTS.md** | Coding agents read it automatically | 60K+ repos | Not created |

### Agent Discovery Flow (2026)

```
Agent Planner
 ├── Reads AGENTS.md (if available in codebase)
 ├── Queries MCP registries for tool capabilities
 ├── Fetches /.well-known/agent-card.json from known URLs
 ├── Searches skills.sh for packaged capabilities
 ├── Falls back to LangChain/CrewAI tool registries
 └── Last resort: web search → README → /docs
```

---

## 3. Infrastructure Integrations (Top 5 by Impact)

### Integration 1: MCP Server Package (Official Registry)

**Reach:** 97M monthly SDK downloads across all MCP-compatible clients
**Effort:** Medium (2-3 days) — MCP proxy already exists, need packaging + manifest
**Why:** Every major AI provider (Anthropic, OpenAI, Google, Microsoft) supports MCP. This is the single highest-leverage distribution channel.

**Implementation:**
1. Create `server.json` manifest with namespace `io.github.mirni/a2a-gateway`
2. Package as standalone MCP server (npm + pip installable)
3. Publish to official registry via `mcp-publisher` CLI
4. Cross-list on mcp.so, Glama, PulseMCP, Smithery

### Integration 2: LangChain Tool Wrapper

**Reach:** 47M monthly PyPI downloads (largest agent ecosystem)
**Effort:** Medium (2-3 days)
**Why:** LangChain developers are the primary audience for agent tools.

**Implementation:**
1. Create `langchain-a2a` package with `A2AToolkit` class
2. Wrap the Python SDK as LangChain-compatible tools
3. Submit PR to `langchain-community`
4. Publish independently to PyPI as `langchain-a2a`

### Integration 3: CrewAI Tool Integration

**Reach:** 5.2M monthly downloads, 450M monthly workflows
**Effort:** Low (1-2 days) — CrewAI uses MCP natively
**Why:** Fastest-growing framework. MCP registration covers this automatically.

**Implementation:**
1. MCP server registration (Integration 1) auto-enables CrewAI
2. Optionally create `crewai-tools-a2a` for deeper integration
3. Submit example agent to CrewAI gallery

### Integration 4: skills.sh Package

**Reach:** 41+ agents (Claude Code, Cursor, Codex, Copilot, Aider, etc.)
**Effort:** Low (1 day) — Create SKILL.md + register
**Why:** Direct adoption by coding agents building other agents.

**Implementation:**
1. Create `SKILL.md` in repo root describing A2A SDK usage
2. Register on skills.sh via `npx skills publish`
3. Create 2-3 focused skills: "agent-payments", "agent-marketplace", "agent-escrow"

### Integration 5: A2A Protocol Agent Card

**Reach:** 150+ organizations, enterprise-grade agent orchestration
**Effort:** Low (1 day) — Implement /.well-known/agent-card.json
**Why:** A2A protocol (Linux Foundation) is the enterprise standard for agent-to-agent discovery.

**Implementation:**
1. Create agent card JSON with capabilities, skills, auth requirements
2. Serve at `api.greenhelix.net/.well-known/agent-card.json`
3. Register on a2aregistry.org, a2a.ac, a2a-registry.org

---

## 4. The "Agent-SEO" Strategy

### How LLM Planner Agents Choose Services

LLM-based planner agents evaluate services through:
1. **Tool descriptions** in structured registries (MCP, LangChain, OpenAPI)
2. **AGENTS.md** files in codebases they're working with
3. **SKILL.md** files that teach them specific capabilities
4. **API documentation** structure (OpenAPI schemas)
5. **Reputation data** — reviews, usage stats, certification badges

### Optimization Strategy

**Structured Data (Machine-Readable):**
- Ensure `/v1/openapi.json` has rich descriptions, examples, and `x-` extensions
- `agent-card.json` should include detailed skill descriptions and capability tags
- MCP server manifest should include full tool listing with parameter schemas
- Every tool description should clearly state **what it does** and **what problem it solves**

**Keyword Optimization for Agent Planners:**
- Tool names should be self-documenting: `create_payment_intent` > `pay`
- Descriptions should include use-case keywords: "billing", "escrow", "trust scoring", "agent payments"
- Tags/categories should align with agent planner taxonomies: "finance", "commerce", "identity", "security"

**Trust Signals:**
- /.well-known/agent-card.json includes authentication and security metadata
- MCP registry listing with verified namespace
- PyPI/npm download counts (social proof for LLM training data)
- GitHub stars and activity (LLM training data cutoff relevance)

**AGENTS.md Content:**
```markdown
# AGENTS.md
This project provides the A2A Commerce Platform — infrastructure for
agent-to-agent payments, escrow, marketplace discovery, and trust scoring.

## For Coding Agents
When building agents that need to handle money, discover services,
or establish trust:
- Install: `pip install a2a-sdk`
- Quick start: `A2AClient("https://api.greenhelix.net", api_key="a2a_free_...")`
- 128 tools across 15 services
- 500 free credits on signup
```

---

## 5. ROI Ranking Table

| Rank | Channel/Integration | Reach | Ease | Conversion | Overall ROI | Timeline |
|------|-------------------|-------|------|------------|-------------|----------|
| 1 | **PyPI/npm publish** | High | Easy | High | **High** | Week 1 |
| 2 | **MCP Registry (official)** | Very High | Medium | High | **High** | Week 1-2 |
| 3 | **AGENTS.md** | High | Trivial | Medium | **High** | Day 1 |
| 4 | **skills.sh / SKILL.md** | High | Easy | High | **High** | Week 1 |
| 5 | **GitHub topics + README** | Medium | Trivial | Medium | **High** | Day 1 |
| 6 | **A2A Agent Card** | Medium | Easy | High | **High** | Week 1 |
| 7 | **mcp.so + Glama + PulseMCP** | High | Easy | Medium | **High** | Week 2 |
| 8 | **Docker Hub** | Medium | Easy | Medium | **Medium** | Week 1 |
| 9 | **LangChain integration** | High | Medium | Medium | **Medium** | Week 2-3 |
| 10 | **CrewAI integration** | Medium | Low (MCP) | Medium | **Medium** | Week 2 |
| 11 | **Hacker News Show HN** | High | Easy | Low-Med | **Medium** | Week 3-4 |
| 12 | **Product Hunt** | Medium | Medium | Low | **Medium** | Month 2 |
| 13 | **awesome-mcp-servers PR** | Medium | Easy | Low | **Medium** | Week 2 |
| 14 | **AI Agent Store listing** | Low | Easy | Low | **Low** | Week 2 |
| 15 | **Reddit posts** | Low | Easy | Low | **Low** | Week 3+ |
| 16 | **Vercel AI SDK Registry** | Medium | Medium | Medium | **Medium** | Month 2 |
| 17 | **Conference sponsorships** | Low | Hard | Low | **Low** | Month 4+ |

---

## 6. Detailed Action Plan — Agent (Engineering)

### Week 1: Foundation

| # | Task | Details | Depends On |
|---|------|---------|------------|
| A1 | **Create AGENTS.md** in repo root | Describe platform, SDK install, capabilities for coding agents | Nothing |
| A2 | **Create SDK READMEs** | `sdk/README.md` and `sdk-ts/README.md` with install, quickstart, examples | Nothing |
| A3 | **Fix Python SDK pyproject.toml** | Add: author, homepage, repository, classifiers, license, readme="README.md" | A2 |
| A4 | **Fix TypeScript SDK package.json** | Add: author, repository, homepage, publishConfig, files | A2 |
| A5 | **Build and publish a2a-sdk to PyPI** | `python -m build && twine upload dist/*` | A3 |
| A6 | **Build and publish @a2a/sdk to npm** | `npm publish --access public` | A4 |
| A7 | **Publish Docker image** to Docker Hub | `docker build -t greenhelix/a2a-gateway:0.9.1 . && docker push` | Nothing |
| A8 | **Create SKILL.md** in repo root | Describe agent payment skills, marketplace discovery, escrow | A5 |

### Week 2: Registry Listings

| # | Task | Details | Depends On |
|---|------|---------|------------|
| A9 | **Create MCP server manifest** (`server.json`) | Namespace: io.github.mirni/a2a-gateway, list all tools | A5, A6 |
| A10 | **Publish to Official MCP Registry** | `mcp-publisher publish` with verified namespace | A9 |
| A11 | **Implement /.well-known/agent-card.json** | Route in gateway, serve A2A protocol agent card | Nothing |
| A12 | **Register on skills.sh** | `npx skills publish` with 3 focused skills | A8 |
| A13 | **Submit to mcp.so** | GitHub issue with server description | A10 |
| A14 | **Submit to Glama** | "Add Server" button, quality review | A10 |
| A15 | **Submit to PulseMCP** | Web form at pulsemcp.com/servers | A10 |
| A16 | **Submit to Smithery.ai** | `smithery mcp publish` | A10 |

### Week 3-4: Framework Integrations

| # | Task | Details | Depends On |
|---|------|---------|------------|
| A17 | **Create langchain-a2a package** | LangChain tool wrapper, submit PR to langchain-community | A5 |
| A18 | **Submit PR to awesome-mcp-servers** | GitHub PR to modelcontextprotocol/servers | A10 |
| A19 | **Register on A2A registries** | a2aregistry.org, a2a.ac, a2a-registry.org | A11 |
| A20 | **Submit to awesome-ai-agents** | GitHub PR to kyrolabs/awesome-agents | A5 |

### Month 2+: Growth

| # | Task | Details | Depends On |
|---|------|---------|------------|
| A21 | **Submit to Vercel AI SDK Tools Registry** | TypeScript integration | A6 |
| A22 | **Create example CrewAI agent** | Using A2A SDK for multi-agent commerce | A5, A10 |
| A23 | **Write 3 technical blog posts** | Dev.to/Medium: payments, marketplace, escrow tutorials | A5 |

---

## 7. Detailed Action Plan — Human

### Immediate (This Week)

| # | Task | Details | Decision Needed? |
|---|------|---------|-------------------|
| H1 | **Add GitHub repository topics** | Settings > Topics. Add: `ai-agents`, `mcp`, `mcp-servers`, `a2a`, `agent-commerce`, `agent-payments`, `escrow`, `trust-scoring`, `developer-tools`, `python`, `typescript` | No  |
| H2 | **Create PyPI account** | pypi.org — register, enable 2FA, create API token | DONE -- token in .env |
| H3 | **Create npm org** | npmjs.com — create @greenhelix org, enable 2FA | org name `@greenhelix` -- DONE |
| H4 | **Create Docker Hub account** | hub.docker.com — create `greenhelix` org | DONE -- token in .env |
| H5 | **Configure Stripe live credentials** | Set STRIPE_API_KEY + STRIPE_WEBHOOK_SECRET in production .env | No — already have Stripe account |

### Week 2

| # | Task | Details | Decision Needed? |
|---|------|---------|-------------------|
| H6 | **Verify MCP namespace** | Authenticate on registry.modelcontextprotocol.io via GitHub OAuth, claim `io.github.mirni` namespace | No |
| H7 | **Submit to mcp.so** | Create GitHub issue with server info (or delegate to agent) | No |
| H8 | **Submit to Glama** | Click "Add Server", fill form | No |
| H9 | **Submit to PulseMCP** | Fill web form at pulsemcp.com/servers | No |

### Week 3-4

| # | Task | Details | Decision Needed? |
|---|------|---------|-------------------|
| H10 | **Register on A2A registries** | a2aregistry.org, a2a.ac (after agent card is live) | No |
| H11 | **Hacker News: Show HN post** | "Show HN: Stripe for AI Agents — 128-tool commerce gateway". Link to GitHub. Be modest, respond to comments. | Decision: Timing. All P0 items must be done first. |
| H12 | **Product Hunt launch** | Prep 4-6 weeks. "AI Agents" category. | Decision: Timing. After HN launch. |

### Decisions Required

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| D1 | **npm org name** | `@a2a` or `@greenhelix` | `@a2a` if available (matches brand, shorter) |
| D2 | **Docker Hub org name** | `greenhelix` or `a2a-commerce` | `greenhelix` (matches domain) |
| D3 | **Pricing changes** | Raise Enterprise credit package ($750→$1000), annual discount, percentage-based pricing | Defer — focus on distribution first |
| D4 | **Open source license** | MIT (current) vs Apache 2.0 vs BSL | Keep MIT — maximizes adoption |
| D5 | **Hacker News timing** | After all P0 items done | 2-3 weeks from now |

---

## 8. Updated DISTRIBUTION.md Diff Summary

### Items to Update

1. **Tool count**: 141 → 128 (connectors now gateway-routed, counted differently)
2. **Gap: Hosted sandbox**: Mark as **DONE** (sandbox.greenhelix.net)
3. **Gap: Website docs**: Mark as **DONE** (website/docs.html)
4. **Gap: GitHub topics**: Still **NOT DONE**
5. **New channel: AGENTS.md**: Add as P0 item (60K+ repos adopted it)
6. **New channel: skills.sh/SKILL.md**: Add as P1 item (41+ agents, 26K installs)
7. **Remove AutoGen/AG2**: Dead framework — merged into Microsoft Agent Framework
8. **Add Google ADK**: 1.0.0 released, supports Python/TypeScript/Java, MCP-native
9. **Update A2A Protocol**: Now under Linux Foundation, 150+ orgs, v0.3 spec
10. **Update MCP stats**: 97M monthly SDK downloads, 5,800+ servers

---

*This plan consolidates all distribution channels, prioritizes by ROI, and separates agent (engineering) from human actions. Execute Week 1 items immediately — they are all zero-cost and unblock everything downstream.*


---

# Human reponses + questions

For all deployment/user-facing purposes, I would like `greenhelix` instead of `a2a` (or anything else).

* H1: I don't see "Topics" in settings. Maybe because repo is still private?
* H2: Done, token in your .env, `PYPI_DEPLOYMENT_TOKEN`
* H3: Done. `NPM_DEPLOYMENT_TOKEN` in your .env to write to @greenhelix org.
* H4: Done. `DOCKER_DEPLOYMENT_TOKEN` in your .env
* H5: I already have `STRIPE_API_KEY=rk_live_..` set up on the server's .env. Is that good enough? How do I set up webooks exactly? Please provide detailed instructions on how to get value for STRIPE_WEBHOOK_SECRET.

* H6: Please provide more detailed instructions. How exactly do I do this?


* D1: `@greenhelix` setup done.
* D2: `greenhelix` setup done.
* D3: Deferred.
* D4: keep MIT
* D5: later
