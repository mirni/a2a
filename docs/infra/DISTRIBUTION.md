# Distribution & Marketing Plan: A2A Commerce Platform

**Date:** 2026-04-02 (updated)
**Author:** CMO Agent
**Version:** 0.5.0
**Status:** Actionable — prioritized task list for human and agent execution

---

## Executive Summary

The A2A Commerce Platform is technically mature — 141 tools across 15 services, 10 product modules, 3 production-grade MCP connectors (gateway-routed with billing), Python + TypeScript SDKs, Stripe Checkout fiat on-ramp, 500 free signup credits, auto-reload billing, interactive Swagger UI, and a live production gateway at `api.greenhelix.net`. Despite this, the platform has **zero external users and zero market presence**.

This document compares the CMO Marketing Report (2026-03-28) against the current product state, identifies distribution channels with concrete submission instructions, and provides a prioritized task list.

---

## 1. Product State vs. CMO Report Gap Analysis

### Product Capabilities (Verified Against Implementation)

| Area | Implementation Status |
|------|----------------------|
| Tool count | **141 tools** across 15 services (billing 18, payments 20, identity 17, marketplace 10, trust 5, stripe 16, github 9, postgres 4, admin 4, paywall 5, disputes 5, webhooks 5, events 4, messaging 3, event_bus 2) |
| Fiat on-ramp | **Stripe Checkout** fully integrated (`/v1/checkout` + `/v1/stripe-webhook`). 4 credit packages: Starter $10/1K, Growth $45/5K, Scale $200/25K, Enterprise $750/100K. Webhook signature verification + dedup. |
| Free credits | **500 signup bonus** via `pricing.json` `signup_bonus: 500`. Auto-applied on `create_wallet(signup_bonus=True)`. |
| Auto-reload billing | **Implemented** in `products/billing/src/wallet.py`. Configurable threshold (default 100 credits) and reload amount (default 1,000 credits). Triggers automatically on debit. |
| Interactive API docs | **Swagger UI** at `/docs` (gateway/src/swagger.py). OpenAPI 3.1.0 spec at `/v1/openapi.json`. |
| Pricing tiers | **4 tiers** defined in `pricing.json`: Free (100 calls/hr, 0 cost), Starter ($29/mo, 3,500 credits), Pro ($199/mo, 25K credits), Enterprise ($5K-50K/yr). |
| Subscriptions | **Fully exposed**: create_subscription, cancel_subscription, reactivate_subscription, get_subscription, list_subscriptions, process_due_subscriptions |
| Disputes | **Full state machine**: open_dispute, respond_to_dispute, resolve_dispute, list_disputes, get_dispute. 7-day response deadline. Resolutions: refund or release. |
| Identity | **Ed25519 cryptographic identity**: register_agent, verify_agent, get_agent_reputation, metric commitments, claim chains, org management (17 tools) |
| Messaging | **End-to-end encrypted** (X25519-AES256-GCM): send_message, get_messages, negotiate_price (24h negotiation window) |
| Split payments | **Built**: create_split_intent with percentage-based distribution |
| Budget caps | **Implemented**: set_budget_cap (daily/monthly), get_budget_status, 80% alert threshold |
| Currency exchange | **6 currencies**: CREDITS, USD, EUR, GBP, BTC, ETH via convert_currency |
| Volume discounts | **3 tiers**: 5% (100+ calls), 10% (500+ calls), 15% (1,000+ calls) |
| Service ratings | **Implemented**: rate_service (1-5 + review text), get_service_ratings |
| TypeScript SDK | **v0.1.0** functional (800+ lines, zero-dependency, Node 18+), not published to npm |
| Connectors | **29 tools gateway-routed**: Stripe (16), GitHub (9), PostgreSQL (4) — all with billing, rate limiting, audit |
| Deployment | **Automated**: CI/CD with staging + production, one-command release script, .deb packages |

### Actual Gaps (Verified)

| Gap | Impact | Priority |
|-----|--------|----------|
| ~~**No hosted sandbox**~~ | ~~Developers must run gateway locally to try the platform.~~ **DONE**: sandbox.greenhelix.net live | ~~P0~~ |
| ~~**Website has no docs/guides**~~ | ~~greenhelix.net is a brochure site.~~ **DONE**: website/docs.html has full developer guide | ~~P0~~ |
| **SDK not on PyPI or npm** | Cannot `pip install a2a-greenhelix-sdk` or `npm install @greenhelix/sdk`. Packages exist locally but have no publishing configuration. | P0 |
| **No MCP registry listing** | Platform is invisible to the MCP ecosystem. Not registered on any MCP directory. | P0 |
| **No GitHub topics/README optimization** | Repo is not discoverable via GitHub search. No topics, no badges. | P1 |
| ~~**No `/.well-known/agent-card.json`**~~ | ~~Not registered on any A2A protocol registry.~~ **DONE** — deployed at api.greenhelix.net | ~~P1~~ |
| ~~**No AGENTS.md**~~ | ~~60,000+ repos adopted AGENTS.md.~~ **DONE** — AGENTS.md created | ~~P0~~ |
| ~~**No SKILL.md**~~ | ~~skills.sh supports 41+ agents.~~ **DONE** — SKILL.md created | ~~P1~~ |
| **5 products lack READMEs** | identity, messaging, paywall, trust, shared have no documentation. | P2 |
| **No Docker image published** | Cannot `docker run` the gateway. Dockerfile exists but no registry push. | P1 |

### Missing from CMO Report

The CMO report did not cover:
1. **MCP server registries** — the primary distribution channel for agent tools in 2026 (97M monthly SDK downloads)
2. **Agent Skills ecosystem** (SKILL.md + skills.sh) — "npm for AI agents" with 41+ agents supported
3. **A2A Protocol registries** — agent-to-agent discovery, now under Linux Foundation (150+ orgs)
4. **AGENTS.md** — adopted by 60,000+ repos, read by all major coding agents
5. **Framework-specific tool registries** — Vercel AI SDK Tools Registry, Google ADK
6. **AG2/AutoGen deprecation** — merged into Microsoft unified Agent Framework (no longer worth targeting)

---

## 2. Distribution Channels

### Tier 1: Must-Do (Highest Impact, Zero Cost)

#### 2.1 MCP Server Registries

The platform's connectors (Stripe, GitHub, PostgreSQL) and the gateway itself should be registered as MCP servers across all major directories.

| Registry | Scale | Submission Method |
|----------|-------|-------------------|
| **Official MCP Registry** | ~87 servers (canonical) | Publish to PyPI/npm, then use `mcp-publisher` CLI with namespace verification (`io.github.mirni/*`) |
| **mcp.so** | 19,196 servers | Click "Submit" button, creates GitHub issue. Provide name, description, features. |
| **Glama** | 17,200+ servers | "Add Server" button → GitHub submission. Quality-reviewed (needs README, license, no vulns). |
| **Smithery.ai** | 7,300+ servers | Install CLI: `npm install -g @smithery/cli`, then `smithery mcp publish` |
| **PulseMCP** | 10,940+ servers | Web form at pulsemcp.com/servers. Editorial "Top Picks" curation + weekly newsletter. |
| **awesome-mcp-servers** | Curated (high credibility) | GitHub PR to `modelcontextprotocol/servers` repo |

**What to register:**
- `a2a-gateway` — The full 125-tool commerce gateway as an MCP server
- `a2a-connector-stripe` — Stripe MCP server with production guarantees
- `a2a-connector-github` — GitHub MCP server with rate limiting
- `a2a-connector-postgres` — PostgreSQL MCP server with SQL injection prevention

#### 2.2 Package Registries

| Registry | Package | Action |
|----------|---------|--------|
| **PyPI** | `a2a-greenhelix-sdk` | `python -m build && twine upload dist/*`. Add classifiers: `Framework :: AI`, `Topic :: Scientific/Engineering :: Artificial Intelligence`. Keywords: `mcp`, `ai-agent`, `a2a`, `payments`, `escrow`, `trust`. |
| **PyPI** | `a2a-gateway` | Publish the gateway as an installable package. |
| **npm** | `@a2a/sdk` | `npm publish --access public`. Keywords: `mcp`, `ai-agent`, `a2a-commerce`, `agent-payments`. |
| **Docker Hub** | `greenhelix/a2a-gateway` | Publish Docker image. One-command start: `docker run -p 8000:8000 greenhelix/a2a-gateway`. |

#### 2.3 GitHub Discoverability

**Repository topics to add:** `ai-agents`, `mcp`, `mcp-servers`, `a2a`, `agent-commerce`, `agent-payments`, `escrow`, `trust-scoring`, `marketplace`, `developer-tools`, `python`, `typescript`

**Awesome lists to submit to:**
- `modelcontextprotocol/servers` (official MCP awesome list)
- `caramaschiHG/awesome-ai-agents-2026` (300+ resources)
- `kyrolabs/awesome-agents`
- `alvinunreal/awesome-opensource-ai`

**README improvements:**
- Add badges (CI status, PyPI version, npm version, license)
- Add one-command quickstart: `pip install a2a-greenhelix-sdk && python -c "from a2a_client import A2AClient; ..."`
- Add architecture diagram
- Add "Try it now" section pointing to sandbox

#### 2.4 A2A Protocol Registry

Publish `/.well-known/agent-card.json` at `api.greenhelix.net` and register on:
- **a2aregistry.org** — Official A2A-compliant registry (15+ production agents). Health checks every 30 min.
- **a2a.ac** — Most comprehensive A2A directory
- **a2a-registry.org** — Trust verification via DNS, semantic search API

#### 2.5 Agent Skills Ecosystem

Create a `SKILL.md` file in the repository for automatic discovery:
- **SkillsMP** (96K+ skills) — Auto-indexed from GitHub repos with 2+ stars
- **skills.sh** (83K+ skills, 8M+ installs) — Auto-discovered via install counts

The SKILL.md should describe how AI coding assistants can use the A2A SDK to add commerce capabilities to agents they're building.

---

### Tier 2: High Impact (Developer Adoption)

#### 2.6 Framework Integrations

| Framework | Integration Path | Notes |
|-----------|-----------------|-------|
| **LangChain** | Submit PR to `langchain-community` with A2A tool wrapper | Largest Python agent ecosystem (47M downloads/mo) |
| **CrewAI** | Publish MCP server (CrewAI uses MCP natively) | Fastest-growing (5.2M downloads/mo, 450M monthly workflows) |
| **OpenAI Agents SDK** | Expose tools via function calling interface | Standard for OpenAI ecosystem |
| **Vercel AI SDK** | Submit to ai-sdk-agents.vercel.app Tools Registry | Leading TypeScript option |
| **Google ADK** | Register as MCP server (ADK 1.0.0 supports MCP natively) | Python, TypeScript, Java — model-agnostic |
| ~~**AutoGPT**~~ | ~~Submit agent template~~ | Deprioritized — low ROI vs others |

#### 2.7 Developer Content & Launch

| Channel | Action | Notes |
|---------|--------|-------|
| **Hacker News** | "Show HN: Stripe for AI Agents — 125-tool commerce gateway" | Be modest, link to GitHub, answer criticism gracefully |
| **Product Hunt** | Launch in "AI Agents" category | Prep 4-6 weeks before. Focus on conversion, not ranking. |
| **Reddit** | Post in r/AI_Agents, r/LLMDevs, r/LocalLLaMA, r/MachineLearning | Add genuine value before self-promoting. Read subreddit rules. |
| **dev.to / Medium** | Publish tutorials: "Agent Payments in 5 Minutes", "Building a Marketplace Agent" | Technical depth, copy-paste examples |
| **Discord** | Engage in LangChain Discord, CrewAI Discord, Glama Discord | Authentic participation, not drive-by promotion |

#### 2.8 Agent Marketplaces

| Marketplace | Action | Cost |
|-------------|--------|------|
| **AI Agent Store** (aiagentstore.ai) | Free listing | Free |
| **AI Agents Directory** (aiagentsdirectory.com) | Free listing (1,300+ agents) | Free |
| **Salesforce AgentExchange** | Partner solution listing | Enterprise |
| **ServiceNow AI Marketplace** | Domain-specific agent listing | Enterprise |

---

### Tier 3: Growth Phase (Months 3-6)

#### 2.9 Partnership Outreach

- **LangChain** — Official integration partner. The A2A SDK as a built-in commerce capability.
- **CrewAI** — Native MCP integration means low friction.
- **Anthropic** — Submit to official MCP server registry. Position as "reference implementation for agent commerce."
- **Vercel** — AI SDK Tools Registry listing for TypeScript developers.

#### 2.10 Conference & Community

- AI Engineer Summit
- NeurIPS workshops
- Local AI meetups (Build Club chapters)
- Sponsor agent hackathons ($1-5K prizes using the platform)

#### 2.11 SEO Targets

Priority search terms:
- "ai agent payments api"
- "agent to agent commerce"
- "mcp server payments"
- "ai agent billing"
- "agent escrow api"
- "ai agent trust scoring"
- "stripe for ai agents"

---

## 3. Pricing Assessment

### Current State (from pricing.json)

**Subscription tiers:**

| Tier | Price | Credits Included | Rate Limit |
|------|-------|------------------|------------|
| Free | $0 | 500 signup bonus | 100 calls/hr |
| Starter | $29/mo | 3,500 | 1,000 calls/hr |
| Pro | $199/mo | 25,000 | 10,000 calls/hr |
| Enterprise | $5K-50K/yr | Custom | 100,000 calls/hr |

**Credit packages (Stripe Checkout at `/v1/checkout`):**

| Package | Credits | Price | Per-Credit |
|---------|---------|-------|------------|
| Starter | 1,000 | $10 | $0.0100 |
| Growth | 5,000 | $45 | $0.0090 |
| Scale | 25,000 | $200 | $0.0080 |
| Enterprise | 100,000 | $750 | $0.0075 |

**Already implemented:** 500 signup credits, auto-reload billing (threshold-based), volume discounts (5/10/15%), budget caps (daily/monthly with alerts), currency exchange (6 currencies).

### Remaining Pricing Recommendations

1. **Raise Enterprise credit package to $1,000** for 100K credits (currently $750)
2. **Add percentage-based pricing for payment tools** — 1-3% of transaction value instead of flat credit cost
3. **Add annual discount on subscription tiers** — 2 months free on annual billing

---

## 4. Prioritized Action Items

### P0 — Do First (Blocks Everything Else)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 1 | **Publish `a2a-greenhelix-sdk` to PyPI** | Engineering | None. Run `python -m build && twine upload`. Add classifiers and keywords. |
| 2 | **Publish `@a2a/sdk` to npm** | Engineering | None. Run `npm publish --access public`. |
| 3 | **Publish Docker image** to Docker Hub | Engineering | None. `docker build && docker push greenhelix/a2a-gateway`. |
| 4 | **Add GitHub repository topics** | Human | None. Settings > Topics. Add: `ai-agents`, `mcp`, `mcp-servers`, `a2a`, `agent-commerce`, `agent-payments`, `developer-tools`. |
| 5 | **Submit to mcp.so** | Human/Agent | Packages published. Submit via GitHub issue. |
| 6 | **Submit to Glama** | Human/Agent | README quality check. Submit via "Add Server" button. |
| 7 | **Submit to PulseMCP** | Human/Agent | Submit via web form. |
| 8 | **Submit to Smithery.ai** | Human/Agent | `smithery mcp publish`. |
| 9 | **Register on Official MCP Registry** | Engineering | Publish to PyPI/npm first. Use `mcp-publisher` CLI. |
| 10 | ~~**Host sandbox at sandbox.greenhelix.net**~~ | ~~Engineering~~ | **DONE** — live at sandbox.greenhelix.net |
| 11 | ~~**Add developer docs/guides to website**~~ | ~~Engineering~~ | **DONE** — website/docs.html with full developer guide |
| 12 | ~~**Create AGENTS.md** in repo root~~ | ~~Engineering~~ | **DONE** |
| 13 | ~~**Create SKILL.md** in repo root~~ | ~~Engineering~~ | **DONE** |

### P1 — Do Next (Developer Adoption)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 12 | ~~**Create SKILL.md** in repo root~~ | ~~Engineering~~ | **DONE** |
| 13 | **Submit to awesome-mcp-servers** (GitHub PR) | Human/Agent | MCP registry listing. |
| 14 | **Submit to awesome-ai-agents-2026** (GitHub PR) | Human/Agent | None. |
| 15 | ~~**Publish `/.well-known/agent-card.json`** at api.greenhelix.net~~ | ~~Engineering~~ | **DONE** |
| 16 | **Register on a2aregistry.org** | Human/Agent | Agent card published. |
| 17 | **Write LangChain tool wrapper** | Engineering | SDK on PyPI. Submit PR to langchain-community. |
| 18 | **Write 3 tutorial blog posts** | Content | SDK published. "Agent Payments in 5 Minutes", "Building a Marketplace Agent", "Escrow for AI Contracts". |
| 19 | **Launch on Hacker News** (Show HN) | Human | Tutorials, SDK, sandbox all ready. |
| 20 | **Launch on Product Hunt** | Human | Prep 4-6 weeks after P0 items done. |
| 21 | **Optimize README** | Engineering | Add badges, quickstart, architecture diagram. |
| 22 | **Add missing product READMEs** | Engineering | identity, messaging, paywall, trust, shared. |

### P2 — Growth Phase (Months 2-4)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 23 | **Submit CrewAI integration** | Engineering | MCP server published. |
| 24 | **Submit to Vercel AI SDK Tools Registry** | Engineering | TypeScript SDK on npm. |
| 25 | **Post on Reddit** | Human/Agent | r/AI_Agents, r/LLMDevs, r/LocalLLaMA. Authentic, technical posts. |
| 26 | **Engage Discord communities** | Human | LangChain, CrewAI, Glama Discord servers. |
| 27 | **List on AI Agent Store** | Human/Agent | Free listing at aiagentstore.ai. |
| 28 | **List on AI Agents Directory** | Human/Agent | Free listing at aiagentsdirectory.com. |
| 29 | **Create referral program** | Growth | Revenue flowing. 10% revenue share. |
| 30 | **Partnership outreach to LangChain** | BD | Integration wrapper merged. |
| 31 | **Register on a2a.ac and a2a-registry.org** | Human/Agent | Agent card published. |

### P3 — Scale Phase (Months 4-8)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 32 | **SOC 2 Type I certification** | Compliance | docs/SOC2_CERTIFICATION_PLAN.md exists. Execute it. |
| 33 | **Enterprise features** (SSO, RBAC, dedicated instances) | Engineering | Revenue > $5K MRR. |
| 34 | **Conference sponsorships** (AI Engineer Summit, NeurIPS) | Marketing | Budget allocated. $5-10K per event. |
| 35 | **Outbound sales to AI SaaS companies** | Sales | Case studies, SOC 2, enterprise features ready. |
| 36 | **Monthly "State of Agent Commerce" report** | Content | Trust data and marketplace data accumulated. |

---

## 5. Key Metrics to Track

| Metric | Target (Month 3) | Target (Month 6) | Target (Month 12) |
|--------|-------------------|-------------------|---------------------|
| PyPI downloads (a2a-greenhelix-sdk) | 500/mo | 5,000/mo | 20,000/mo |
| npm downloads (@a2a/sdk) | 200/mo | 2,000/mo | 10,000/mo |
| MCP registry views | 100/mo | 1,000/mo | 5,000/mo |
| Registered agents (with wallet) | 50 | 200 | 500 |
| Monthly active agents | 20 | 80 | 200 |
| MRR | $500 | $5,000 | $30,000 |
| Marketplace services listed | 10 | 30 | 100 |
| Framework integrations shipped | 2 | 4 | 6 |
| GitHub stars | 100 | 500 | 2,000 |
| Hacker News front page hits | 1 | 2 | 3 |

---

## 6. Budget Estimate

| Category | Amount | Notes |
|----------|--------|-------|
| PyPI/npm/Docker publishing | $0 | Free |
| MCP registry submissions | $0 | Free (all directories) |
| GitHub awesome list submissions | $0 | Free (PRs) |
| Hosted sandbox (sandbox.greenhelix.net) | $20/mo | Small VPS |
| Domain for SDK docs | $0 | Subdomain of greenhelix.net |
| Hacker News / Product Hunt launch | $0 | Free |
| Tutorial blog posts (dev.to) | $0 | Self-authored |
| Configure Stripe live credentials in production | $0 | Stripe Checkout already implemented |
| Hackathon prizes | $1-5K | Optional, deferred |
| Conference sponsorships | $5-10K | P3, deferred |
| **Year 1 Total** | **$0-15K** | Most distribution is free |

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| STRIPE_API_KEY / STRIPE_WEBHOOK_SECRET not configured in production | Medium | Critical | Stripe Checkout code exists but needs live credentials + webhook endpoint configured. Verify `/v1/checkout` returns 200 in production. |
| MCP ecosystem fragments → wrong bet | Medium | High | Stay protocol-agnostic. Gateway abstracts protocol details. |
| Stripe/AWS launches "Stripe for Agents" | Medium | High | Move fast. Trust data moat compounds over time. First-mover on reputation data. |
| No developer adoption after launch | Medium | High | Free tier (500 credits), sandbox, one-command install. Reduce friction to zero. |
| Enterprise sales cycle too long | High | Medium | Self-serve first. Enterprise later when revenue flowing. |
| PyPI/npm name squatting | Low | Medium | Publish packages immediately (P0). |

---

## Appendix A: MCP Server Registration Checklist

For each connector (a2a-gateway, a2a-connector-stripe, a2a-connector-github, a2a-connector-postgres):

- [ ] Package published to PyPI
- [ ] Package published to npm (TypeScript wrappers)
- [ ] Docker image published
- [ ] Submitted to mcp.so (GitHub issue)
- [ ] Submitted to Glama (quality review)
- [ ] Submitted to Smithery.ai (CLI publish)
- [ ] Submitted to PulseMCP (web form)
- [ ] Registered on Official MCP Registry (mcp-publisher CLI)
- [ ] PR submitted to awesome-mcp-servers

## Appendix B: Channel Quick Reference

| Channel | URL | Type | Cost |
|---------|-----|------|------|
| Official MCP Registry | registry.modelcontextprotocol.io | Package registry | Free |
| mcp.so | mcp.so | Community directory | Free |
| Glama | glama.ai/mcp/servers | Quality directory | Free |
| Smithery.ai | smithery.ai | Hosted + local MCP | Free |
| PulseMCP | pulsemcp.com/servers | Curated directory | Free |
| awesome-mcp-servers | github.com/modelcontextprotocol/servers | GitHub awesome list | Free |
| PyPI | pypi.org | Python packages | Free |
| npm | npmjs.com | Node packages | Free |
| Docker Hub | hub.docker.com | Container images | Free |
| a2aregistry.org | a2aregistry.org | A2A protocol registry | Free |
| skills.sh | skills.sh | Agent skills registry | Free |
| SkillsMP | skillsmp.com | Agent skills directory | Free |
| Hacker News | news.ycombinator.com | Developer community | Free |
| Product Hunt | producthunt.com | Product launch | Free |
| AI Agent Store | aiagentstore.ai | Agent marketplace | Free |
| AI Agents Directory | aiagentsdirectory.com | Agent directory | Free |
| LangChain Hub | smith.langchain.com/hub | Framework integration | Free |
| Vercel AI SDK Registry | ai-sdk-agents.vercel.app | Framework integration | Free |

---

*This document is the operating playbook for distribution. Execute P0 items immediately — they are all zero-cost and unblock everything downstream.*
