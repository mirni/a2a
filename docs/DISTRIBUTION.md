# Distribution & Marketing Plan: A2A Commerce Platform

**Date:** 2026-03-31
**Author:** CMO Agent
**Version:** 0.4.0
**Status:** Actionable — prioritized task list for human and agent execution

---

## Executive Summary

The A2A Commerce Platform is technically mature — 125 tools, 10 product modules, 3 production-grade MCP connectors, Python + TypeScript SDKs, 159 test files, and a live production gateway at `api.greenhelix.net`. Despite this, the platform has **zero external users and zero market presence**.

This document compares the CMO Marketing Report (2026-03-28) against the current product state, identifies distribution channels with concrete submission instructions, and provides a prioritized task list.

---

## 1. Product State vs. CMO Report Gap Analysis

### Strong Points (Improved Since Report)

| Area | CMO Report State (03-28) | Current State (03-31) |
|------|--------------------------|----------------------|
| Tool count | 108 tools | **125 tools** (billing 18, payments 20, identity 17, marketplace 10, trust 5, connectors 29, admin 4, paywall 5, disputes 5, webhooks 5, events 4, messaging 3) |
| Subscriptions | "Not tool-exposed" | **Fully exposed**: create_subscription, cancel_subscription, reactivate_subscription, get_subscription, list_subscriptions, process_due_subscriptions |
| Disputes | Not mentioned | **Fully built**: open_dispute, respond_to_dispute, resolve_dispute, list_disputes, get_dispute |
| Identity | "No agent identity" | **Full module**: register_agent, verify_agent, get_agent_reputation, Ed25519 keys, metric commitments, claim chains, org management |
| Messaging | Not mentioned | **Built**: send_message, get_messages, negotiate_price |
| Split payments | "Absent" | **Built**: create_split_intent |
| TypeScript SDK | "Missing" | **v0.1.0 exists** (zero-dependency, Node 18+) |
| Connectors | "Isolated, not gateway-routed" | **Gateway-routed**: all 29 connector tools in catalog with billing, rate limiting, audit |
| Marketplace | "Basic CRUD" | **Enhanced**: service ratings, agent search, strategy marketplace, analytics |
| Deployment | Manual | **Automated**: CI/CD with staging + production, one-command release script |

### Weak Points (Still Unresolved)

| Gap | Impact | Priority |
|-----|--------|----------|
| **No fiat on-ramp** | Cannot collect real money. Revenue = $0 until this is built. | P0 |
| **No hosted sandbox** | Developers must run gateway locally to try the platform. | P0 |
| **No interactive API docs** | OpenAPI spec exists but no Swagger UI at the API endpoint. | P1 |
| **No free credits on signup** | Cold-start friction for new agents. | P1 |
| **No auto-reload billing** | Agents hit zero balance and stop working. | P1 |
| **Website has no docs/guides** | greenhelix.net is a brochure site with zero developer content. | P0 |
| **SDK not on PyPI or npm** | Cannot `pip install a2a-sdk` or `npm install @a2a/sdk`. | P0 |
| **No MCP registry listing** | Platform is invisible to the MCP ecosystem. | P0 |
| **No GitHub topics/README optimization** | Repo is not discoverable via GitHub search. | P1 |
| **5 products lack READMEs** | identity, messaging, paywall, trust, shared have no documentation. | P2 |

### Missing from CMO Report

The CMO report did not cover:
1. **MCP server registries** — the primary distribution channel for agent tools in 2026
2. **Agent Skills ecosystem** (SKILL.md) — new "npm for AI agents" with 96K+ skills indexed
3. **A2A Protocol registries** — agent-to-agent discovery via `/.well-known/agent-card.json`
4. **Framework-specific tool registries** — Vercel AI SDK Tools Registry, Google ADK Cloud API Registry
5. **Concrete submission processes** for each channel

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
| **PyPI** | `a2a-sdk` | `python -m build && twine upload dist/*`. Add classifiers: `Framework :: AI`, `Topic :: Scientific/Engineering :: Artificial Intelligence`. Keywords: `mcp`, `ai-agent`, `a2a`, `payments`, `escrow`, `trust`. |
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
- Add one-command quickstart: `pip install a2a-sdk && python -c "from a2a_client import A2AClient; ..."`
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
| **LangChain** | Submit PR to `langchain-community` with A2A tool wrapper | Largest Python agent ecosystem |
| **CrewAI** | Publish MCP server (CrewAI uses MCP natively) | Submit PR to `crewai-tools` |
| **OpenAI Agents SDK** | Expose tools via function calling interface | 14.7M monthly PyPI downloads |
| **Vercel AI SDK** | Submit to ai-sdk-agents.vercel.app Tools Registry | TypeScript-first, 20M+ monthly downloads |
| **Google ADK** | Register in Cloud API Registry as MCP server | Growing enterprise adoption |
| **AutoGPT** | Submit agent template to AutoGPT marketplace | Built into platform |

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

## 3. Pricing Assessment (Current vs. Recommended)

### Current State (from catalog.json)

Tools are priced in credits. Credit packages:

| Package | Credits | Price | Per-Credit |
|---------|---------|-------|------------|
| Starter | 1,000 | $10 | $0.0100 |
| Growth | 5,000 | $45 | $0.0090 |
| Scale | 25,000 | $200 | $0.0080 |
| Enterprise | 100,000 | $750 | $0.0075 |

### Recommendations (Unchanged from CMO Report)

1. **Add 500 free credits on signup** — essential for removing cold-start friction
2. **Add auto-reload** — agents set threshold, wallet auto-refills
3. **Raise Enterprise to $1,000** for 100K credits
4. **Add monthly plans:** Starter $29/mo (3,500 credits), Pro $199/mo (25,000 credits), Enterprise custom
5. **Switch payment tools to percentage-based pricing** — 1-3% of transaction value instead of flat fee

---

## 4. Prioritized Action Items

### P0 — Do First (Blocks Everything Else)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 1 | **Publish `a2a-sdk` to PyPI** | Engineering | None. Run `python -m build && twine upload`. |
| 2 | **Publish `@a2a/sdk` to npm** | Engineering | None. Run `npm publish --access public`. |
| 3 | **Publish Docker image** to Docker Hub | Engineering | None. `docker build && docker push greenhelix/a2a-gateway`. |
| 4 | **Add GitHub repository topics** | Human | None. Settings > Topics. Add: `ai-agents`, `mcp`, `mcp-servers`, `a2a`, `agent-commerce`, `agent-payments`, `developer-tools`. |
| 5 | **Submit to mcp.so** | Human/Agent | Packages published. Submit via GitHub issue. |
| 6 | **Submit to Glama** | Human/Agent | README quality check. Submit via "Add Server" button. |
| 7 | **Submit to PulseMCP** | Human/Agent | Submit via web form. |
| 8 | **Submit to Smithery.ai** | Human/Agent | `smithery mcp publish`. |
| 9 | **Register on Official MCP Registry** | Engineering | Publish to PyPI/npm first. Use `mcp-publisher` CLI. |
| 10 | **Host sandbox at sandbox.greenhelix.net** | Engineering | Provision staging-like instance with pre-loaded demo data and free API keys. |
| 11 | **Add Swagger UI at api.greenhelix.net/docs** | Engineering | OpenAPI spec exists. Add `swagger-ui-dist` or redirect to rendered spec. |
| 12 | **Build fiat on-ramp (Stripe Checkout)** | Engineering | Stripe connector exists. Wire Checkout → deposit(). |

### P1 — Do Next (Developer Adoption)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 13 | **Create SKILL.md** in repo root | Engineering | SDK published. Describe how to use A2A SDK for commerce. |
| 14 | **Submit to awesome-mcp-servers** (GitHub PR) | Human/Agent | MCP registry listing. |
| 15 | **Submit to awesome-ai-agents-2026** (GitHub PR) | Human/Agent | None. |
| 16 | **Publish `/.well-known/agent-card.json`** at api.greenhelix.net | Engineering | A2A protocol spec compliance. |
| 17 | **Register on a2aregistry.org** | Human/Agent | Agent card published. |
| 18 | **Write LangChain tool wrapper** | Engineering | SDK on PyPI. Submit PR to langchain-community. |
| 19 | **Write 3 tutorial blog posts** | Content | SDK published. "Agent Payments in 5 Minutes", "Building a Marketplace Agent", "Escrow for AI Contracts". |
| 20 | **Launch on Hacker News** (Show HN) | Human | Tutorials, SDK, sandbox all ready. |
| 21 | **Launch on Product Hunt** | Human | Prep 4-6 weeks after P0 items done. |
| 22 | **Add 500 free credits on signup** | Engineering | Fiat on-ramp or pre-provisioned demo. |
| 23 | **Optimize README** | Engineering | Add badges, quickstart, architecture diagram. |
| 24 | **Add missing product READMEs** | Engineering | identity, messaging, paywall, trust, shared. |

### P2 — Growth Phase (Months 2-4)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 25 | **Submit CrewAI integration** | Engineering | MCP server published. |
| 26 | **Submit to Vercel AI SDK Tools Registry** | Engineering | TypeScript SDK on npm. |
| 27 | **Post on Reddit** | Human/Agent | r/AI_Agents, r/LLMDevs, r/LocalLLaMA. Authentic, technical posts. |
| 28 | **Engage Discord communities** | Human | LangChain, CrewAI, Glama Discord servers. |
| 29 | **List on AI Agent Store** | Human/Agent | Free listing at aiagentstore.ai. |
| 30 | **List on AI Agents Directory** | Human/Agent | Free listing at aiagentsdirectory.com. |
| 31 | **Build auto-reload billing** | Engineering | Fiat on-ramp working. |
| 32 | **Add monthly subscription plans** | Engineering | Auto-reload working. |
| 33 | **Create referral program** | Growth | Revenue flowing. 10% revenue share. |
| 34 | **Partnership outreach to LangChain** | BD | Integration wrapper merged. |
| 35 | **Register on a2a.ac and a2a-registry.org** | Human/Agent | Agent card published. |

### P3 — Scale Phase (Months 4-8)

| # | Task | Owner | Dependency |
|---|------|-------|------------|
| 36 | **SOC 2 Type I certification** | Compliance | docs/SOC2_CERTIFICATION_PLAN.md exists. Execute it. |
| 37 | **Enterprise features** (SSO, RBAC, dedicated instances) | Engineering | Revenue > $5K MRR. |
| 38 | **Conference sponsorships** (AI Engineer Summit, NeurIPS) | Marketing | Budget allocated. $5-10K per event. |
| 39 | **Outbound sales to AI SaaS companies** | Sales | Case studies, SOC 2, enterprise features ready. |
| 40 | **Monthly "State of Agent Commerce" report** | Content | Trust data and marketplace data accumulated. |

---

## 5. Key Metrics to Track

| Metric | Target (Month 3) | Target (Month 6) | Target (Month 12) |
|--------|-------------------|-------------------|---------------------|
| PyPI downloads (a2a-sdk) | 500/mo | 5,000/mo | 20,000/mo |
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
| Stripe Checkout integration (fiat on-ramp) | $0 | Engineering time only |
| Hackathon prizes | $1-5K | Optional, deferred |
| Conference sponsorships | $5-10K | P3, deferred |
| **Year 1 Total** | **$0-15K** | Most distribution is free |

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Fiat on-ramp not built → $0 revenue | High | Critical | P0 priority. Existing Stripe connector + deposit() makes this straightforward. |
| MCP ecosystem fragments → wrong bet | Medium | High | Stay protocol-agnostic. Gateway abstracts protocol details. |
| Stripe/AWS launches "Stripe for Agents" | Medium | High | Move fast. Trust data moat compounds over time. First-mover on reputation data. |
| No developer adoption after launch | Medium | High | Free tier, sandbox, one-command install. Reduce friction to zero. |
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
