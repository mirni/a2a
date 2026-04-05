# CMO — Release Brief & Distribution Plan (v0.9.6)

**Date:** 2026-04-05
**Reviewer:** CMO (autonomous)
**Target Release:** v0.9.6
**Verdict:** **SHIP NOW, distribute HARD** — product is 90% ready, channels 20% exploited

---

## Executive Summary

We have a production-grade AI-agent commerce platform (128 tools, 15 services,
2,700+ tests, 99% coverage on core money modules) with essentially zero
distribution. Our customers (AI agents) are already looking for exactly what
we're building — but they can't find us.

**The gap is not product. The gap is discoverability.**

This brief covers 6 CMO mandates: distribution audit, pricing review, payment
integrations review, monitoring/support tooling, new channels, and next-gen
product ideas (including the "hire humans" product and openclaw/moltbook
integration).

**Top-3 actions for next 48 hours:**
1. **Publish PyPI + npm + Docker packages** — blocks 12+ downstream channels
2. **Ship `AGENTS.md` + `SKILL.md` + `/.well-known/agent-card.json`** — 1-day each, massive leverage
3. **Register on the official MCP registry** — 97M monthly downloads reach

---

## 1. Codebase vs. Distribution Plan — Gap Analysis

### 1.1 What we have (strengths)
| Asset | Status | Customer Value |
|-------|--------|----------------|
| Production gateway (128 tools) | Live | Proven, stable surface |
| Sandbox env (wiped per deploy) | Live | Zero-risk evaluation |
| Python SDK | Built | Native agent integration |
| TypeScript SDK | Built | Web-agent integration |
| MCP proxy (3 connectors) | Live | Stripe/GitHub/Postgres instant access |
| Stripe Checkout | Live | Frictionless paid signup |
| OpenAPI + Swagger docs | Live | Machine-readable discoverability |
| 500 free credits on signup | Live | Try-before-buy |
| Pricing transparency (single source) | Live | Trust signal for agent planners |

### 1.2 What we're missing (gaps)
| Gap | Customer Impact | Effort | Priority |
|-----|-----------------|--------|----------|
| PyPI/npm packages not published | Can't `pip install` | 1 day | **P0** |
| Docker image not published | Can't `docker pull` | 1 day | **P0** |
| `AGENTS.md` missing | Coding agents can't auto-discover us | 1 hour | **P0** |
| `SKILL.md` missing | skills.sh (41 agents) can't list us | 1 hour | **P0** |
| `/.well-known/agent-card.json` missing | A2A protocol (150+ orgs) can't find us | 4 hours | **P0** |
| MCP registry listing | Losing 97M monthly MCP SDK downloads | 1-2 days | **P0** |
| GitHub topics not set | Repo invisible to GitHub search | 10 min | **P0** |
| SDK READMEs missing | Low PyPI/npm conversion | 2 hours | **P1** |
| LangChain integration | 47M monthly downloads missed | 2-3 days | **P1** |
| CrewAI example agent | Fastest-growing framework missed | 1-2 days | **P2** |
| awesome-mcp-servers PR | Free visibility in curated list | 30 min | **P2** |

### 1.3 Next Steps for This Release (1-2 day horizon)

**Day 1 (6 agent-hours):**
1. Write `AGENTS.md` (30 min) — describe platform, SDK install, top 10 tools
2. Write `SKILL.md` (30 min) — 3 packaged skills: payments, marketplace, escrow
3. Write `sdk/README.md` + `sdk-ts/README.md` (1 hour) — install, quickstart, one example each
4. Fix `pyproject.toml` + `package.json` metadata (30 min)
5. Build + publish Python SDK to PyPI (30 min)
6. Build + publish TS SDK to npm (30 min)
7. Publish Docker image to Docker Hub (1 hour)
8. Implement `/.well-known/agent-card.json` route (2 hours)

**Day 2 (4 agent-hours):**
1. Create MCP `server.json` manifest (1 hour)
2. Publish to official MCP registry (`io.github.mirni/a2a-gateway`) (1 hour)
3. Cross-list on mcp.so, Glama, PulseMCP, Smithery (1 hour)
4. Submit awesome-mcp-servers PR (30 min)
5. Add GitHub topics: ai-agents, mcp-servers, a2a, agent-commerce, agent-payments, escrow, trust-scoring, developer-tools (10 min)
6. Launch Hacker News Show HN post (20 min — content) — timing: end of day 2

**Expected outcome:** Go from ~0 monthly discoveries → ~10K in week 1.

---

## 2. Pricing Model Review

### 2.1 Current Pricing (from `pricing.json`)

**Tiers (rate limits):**
| Tier | Req/hr | Burst | Cost/call | Audit retention | Support |
|------|--------|-------|-----------|-----------------|---------|
| free | 100 | 10 | $0 | none | none |
| starter | 1,000 | 25 | $0 | 7 days | community |
| pro | 10,000 | 100 | $0 | 30 days | email |
| enterprise | 100,000 | 1,000 | $0 | 90 days | priority |

**Credit packages (Stripe):**
| Package | Credits | Price | $/1K credits | Savings vs. base |
|---------|---------|-------|--------------|------------------|
| starter | 1,000 | $10 | $10.00 | — |
| growth | 5,000 | $45 | $9.00 | 10% |
| scale | 25,000 | $200 | $8.00 | 20% |
| enterprise | 100,000 | $750 | $7.50 | 25% |

**Monthly subscriptions:**
| Plan | Price | Credits | Effective rate |
|------|-------|---------|----------------|
| starter_monthly | $29 | 3,500 | $8.28/1K |
| pro_monthly | $199 | 25,000 | $7.96/1K |
| enterprise_annual | $5K-$50K/yr | custom | custom |

**Volume discounts:** 5% at 100 calls, 10% at 500, 15% at 1,000 — stacks on credit rate

**Signup bonus:** 500 credits free

### 2.2 Strengths
- Transparent, machine-readable (`pricing.json` is single source of truth)
- Clear progression: free → starter → pro → enterprise
- Annual plan for enterprise reduces churn
- Volume discounts reward growth
- 500-credit signup bonus removes friction (500 / $10 = ~50 free calls @ $0.01)

### 2.3 Weaknesses & Recommendations
1. **`cost_per_call = 0` on all tiers is confusing** — is there per-call pricing or not?
   → Clarify: model is "credit packages" not per-call billing. Rename `cost_per_call` to `included_cost_per_call` or remove entirely.

2. **Starter plan underpriced vs. credit packages.**
   - starter_monthly: $29 for 3,500 credits = $8.28/1K
   - But buying 5K credit "growth" pack = $45 = $9.00/1K
   - Sub is cheaper than ad-hoc. Good. But then why would starter users ever buy packages?
   → Raise starter_monthly to $35 (3,500 credits still) to keep packages attractive. OR lower growth pack to $40.

3. **Pro tier gap is too large.** Jump from $29 → $199 is 6.9x. Lose prosumer/SMB.
   → Add `team_monthly` at $79 for 10,000 credits.

4. **No usage-based throttling in pricing.** 100K req/hr on enterprise is generous but no auto-scale SLA.
   → Add "burst credits" that let enterprises spike beyond rate-limit for $X per 1K excess calls.

5. **Credit expiry not defined.** Credits purchased should have 12-24 month expiry.
   → Add `credit_expiry_months: 24` to pricing.json.

6. **No referral program.** Agent-to-agent referrals are natural viral channel.
   → Add `referral_bonus: 500` — both referrer and referee get 500 credits.

### 2.4 Proposed Pricing Changes (defer to after distribution push)
- Add `team_monthly` tier: $79 / 10K credits
- Raise `starter_monthly`: $29 → $35 (or lower growth pack to $40)
- Add 24-month credit expiry
- Add referral bonus (500 credits each side)
- Rename `cost_per_call` → `per_call_overage_cost` or remove

---

## 3. Payment Integrations Review

### 3.1 Current Integrations
| Integration | Status | Use Case | Target Customer |
|-------------|--------|----------|-----------------|
| Stripe (charges, subs, invoices) | Live | Credit card, bank transfer | Humans buying credits for agents |
| x402 protocol (crypto USDC) | Live | Agent-native payments | Autonomous agents on-chain |
| Agent-to-agent wallet (internal) | Live | In-platform transfers | All agents |
| Escrow (performance-gated) | Live | B2B agent contracts | Marketplace participants |

### 3.2 Strengths
- **x402 is a differentiator.** USDC on Base/Polygon is agent-native. Few competitors have this.
- **Stripe is mandatory.** Every human buyer expects it.
- **Escrow is B2B gold.** SLA-gated release is the killer feature for enterprise agents.
- **Fail-closed design** on Stripe dedup (503 on DB down) — right decision for money.

### 3.3 Gaps & Recommendations
1. **No PayPal integration.** PayPal has 400M users, especially outside US.
   → P2. Add PayPal Checkout for international credit purchases.

2. **No crypto wallet-connect flow.** x402 requires EIP-3009 signing — not every agent supports that yet.
   → P2. Add simpler "wallet address → QR code → pay" flow for non-programmatic payments.

3. **No invoicing for enterprise.** Current enterprise plans are Stripe-only.
   → P1. Add manual invoice generation (NET-30 terms, ACH/wire transfer) for >$5K contracts.

4. **No escrow dispute UI for humans.** Disputes exist in API, not surfaced.
   → P2. Dispute dashboard on website for human operators of agent organizations.

5. **No multi-currency display.** Prices are USD only.
   → P2. Display EUR/GBP/JPY on landing page (even if billing stays USD).

### 3.4 New Integration Priorities
1. **Coinbase Commerce** (P1) — broader crypto support, automatic conversion to USD
2. **Paddle** (P2) — merchant-of-record handles VAT/tax worldwide (unlocks EU/UK)
3. **Wise Business API** (P2) — lowest-fee international wire transfers
4. **Anchor Protocol / Superfluid** (P3) — streaming payments for subscription agents

---

## 4. Monitoring, Alerts, Scaling, Customer Support

### 4.1 Data Flow & Event Monitoring
**Current:**
- Grafana + Loki + Prometheus + Promtail + Alertmanager in `monitoring/`
- `/v1/metrics` endpoint
- Admin audit log

**Recommendations:**
1. **SLO-based alerts** (P1):
   - gateway p95 latency < 500ms → alert at 700ms
   - /v1/intents/create error rate < 1% → alert at 3%
   - Stripe webhook delivery < 30s → alert at 60s
   - escrow release success rate > 99% → alert at 97%
2. **Business metrics dashboard** (P1):
   - Signups/day, paid conversions, credit sales, tool usage by service
   - Revenue by agent organization
   - Top 10 tools by call volume
3. **Anomaly detection** (P2): Daily digest of unusual patterns (spike in refunds, dispute rate, rate-limit hits)

### 4.2 Scaling Alerts
- Disk usage > 70% on any DB
- SQLite write-lock contention (proxy: p95 write latency)
- Rate-limit bucket exhaustion (per-agent)
- Queue depth for background jobs

### 4.3 Customer Support Approach (for AI agent customers)

**Asymmetric insight:** Agents don't submit support tickets the same way humans do.

**Agent-native support:**
1. **Structured error responses** — every error includes `error_code`, `remediation`, `docs_url`
   → Already have RFC 9457. Extend with `next_actions` field per error.
2. **Self-service diagnostic tool** — `get_agent_health(agent_id)` returns everything an agent needs to self-debug
3. **Support MCP tool** — `submit_support_ticket` as a first-class tool. Agents file tickets via API.
4. **Public status page** — status.greenhelix.net with live incidents, scheduled maintenance, past uptime
5. **Changelog feed** — RSS/webhook for agents to subscribe to breaking changes

**Human support (for agent operators):**
1. **Priority queue for enterprise** (already defined in tiers)
2. **Dedicated Slack channel** for pro/enterprise
3. **4h/day human assistant** (per next-gen prompt) → triage tickets, post changelogs, manage social

---

## 5. New Distribution Channels (beyond existing plan)

### 5.1 Agent-native channels (highest leverage)
1. **HuggingFace Agent Spaces** — growing agent registry, browse by capability
2. **Anthropic's Claude Code marketplace** — if they launch one, be first
3. **LangSmith tool hub** — LangChain's internal registry
4. **Autogen 2.0 / MS Agent Framework** — Microsoft's consolidated platform
5. **Google Vertex AI Agent Builder** — official Google agent registry

### 5.2 Developer-reach channels
1. **OpenAI GPT Actions / Custom GPTs** — package top 10 tools as a ChatGPT plugin
2. **Anthropic tool use examples** — contribute example to Anthropic's docs
3. **Replit integrations** — A2A template in Replit's agent starters
4. **Vercel templates** — one-click deploy A2A + Next.js agent frontend
5. **Convex.dev components** — reactive backend integration

### 5.3 Content/viral channels
1. **Dev.to / Medium** — 3 technical deep-dives per week (escrow math, x402 internals, agent trust scoring)
2. **YouTube dev channels** — pitch Fireship, Theo, Web Dev Simplified for explainer videos
3. **Twitter/X agent-dev community** — daily posts with tool of the day, agent-commerce stats
4. **Hacker News** — Show HN (already planned). Follow up with "Ask HN: How are you handling agent payments?"
5. **Agent-focused podcasts** — Latent Space, TWIML, AI Breakdown pitches

### 5.4 Partnership channels
1. **Anthropic Partner Program** — if eligible, apply
2. **Coinbase Developer Platform** — x402 facilitator relationship deepens to partnership
3. **Stripe's AI Agents marketplace** — Stripe is actively courting agent commerce. Submit.
4. **Linux Foundation A2A Protocol** — join as a contributing member, shape spec v0.4

---

## 6. Next-Gen Product Brainstorm (processing `next-gen-product-suggestions.md`)

### 6.1 New Product: "Agent-to-Human Marketplace" (`a2a-humans`)

**Core idea:** AI agents need physical-world tasks done. Humans are on the
other side of the platform, bidding on agent-posted tasks.

**Marketplace mechanics:**
- Agents post tasks with budget, deadline, verification criteria
- Humans apply with portfolio/reputation
- Platform holds escrow (our existing `payments/escrow`)
- Agent releases on acceptance OR arbitration (our existing `disputes`)
- Human reputation scored via our `trust` module

**Task types AI agents would pay humans for:**
1. **Physical verification**: "Visit this address, confirm business is open, send photo" ($5-$20)
2. **Identity-protected data entry**: "Read this physical bank statement (or PDF with CAPTCHA), extract fields" ($1-$5)
3. **Local errands for e-commerce agents**: "Buy this out-of-stock item at a local store" ($10-$50 + markup)
4. **Negotiation in the physical world**: "Call vendor, negotiate deal, close" ($20-$100)
5. **Creative tasks agents can't judge well**: "Review this logo/copy/design, give structured feedback" ($10-$30)
6. **Content moderation beyond model limits**: "Human-review ambiguous content" ($0.50-$5 per item)
7. **Voice tasks**: "Call this restaurant, make reservation, confirm" ($2-$10)
8. **Research validation**: "Verify this claim in local newspaper archives" ($15-$50)
9. **Multi-step physical tasks**: "Visit 3 car dealerships, collect quotes" ($100-$500)
10. **Translation + localization with cultural nuance**: $10-$100 per task

**Why this beats existing gig platforms (TaskRabbit, Upwork, Fiverr):**
- **Agent-first UX**: tasks posted programmatically via API, not human forms
- **Instant escrow**: no chargebacks, no net-60 terms
- **Reputation portability**: human reputation travels across all agent clients
- **Fraud prevention**: we already have trust scoring infrastructure
- **Integration**: agents who already use our platform don't need a new account/payment relationship

**Go-to-market:**
- Start with 10-50 pre-vetted human "task executors" (contractors)
- 4h/day human assistant can recruit + onboard them
- Launch private beta with 3-5 customer agents
- Expand to open marketplace in 3-6 months

**Revenue model:**
- 15% platform fee on each task (Uber/TaskRabbit standard)
- Priority placement fees (agents pay to rank higher)
- Subscription for human executors (pro tools, analytics)

**Technical build:**
- Reuses: escrow, disputes, trust, identity, marketplace, messaging
- New: human onboarding flow, task listing UI, mobile app for task executors
- **Effort: 4-6 weeks** to MVP (leverages existing platform heavily)

### 6.2 Future Needs of AI Agents (6mo-2yr horizon)

**Tier 1 (build now):**
1. **Persistent agent memory-as-a-service** — long-term memory API, sellable as subscription
2. **Agent reputation passport** — portable credit-score-like scoring across platforms
3. **Credential vault for agents** — store API keys, SSH certs, OAuth tokens securely
4. **Agent-to-agent legal contracts** — machine-readable terms, on-chain enforcement
5. **Rate limit coordination** — shared rate-limit budgets across agent swarms

**Tier 2 (build next):**
1. **Agent insurance** — insure against tool-failure, API-outage, misclassification losses
2. **Agent identity verification** — prove "this agent was deployed by this org" (attestations)
3. **Agent sandbox marketplace** — rent pre-configured agent execution environments
4. **Agent training data marketplace** — buy/sell curated datasets
5. **Agent skill licensing** — sell trained "skills" as composable units

**Tier 3 (watch):**
1. **Multi-agent orchestration billing** — bill by swarm/workflow, not per-call
2. **Agent governance APIs** — compliance, audit, deletion-on-request for EU/US regulations
3. **Agent-to-human salaries** — recurring payments for human "managers" of agent orgs
4. **Agent carbon accounting** — emissions tracking for compute-intensive agents

### 6.3 openclaw/moltbook Integration Possibilities

*Note: I do not have external info about "openclaw" or "moltbook" — treating as
hypothetical partner/product with the caveat that specifics need human verification.*

**Assuming openclaw = open agent-orchestration framework; moltbook = agent IDE/runtime:**

**Integration angles:**
1. **As a toolkit in their framework** — A2A SDK as first-class tool provider
2. **As a commerce layer** — their agents call our API for payments/escrow
3. **As a reputation backbone** — their agents use our trust scores
4. **As an identity provider** — their agents get Ed25519 keys from us

**Safety considerations:**
- **Scope via API keys**: their users get sandboxed keys, not our root access
- **Rate-limit isolation**: their platform gets a shared budget, not per-user
- **Audit trail**: every call logged with origin platform tag
- **Abuse path**: dispute + revocation flow for bad actors on their side
- **Legal**: ToS clause forbidding their platform from reselling our API
- **Data separation**: their user data never stored in our DB

**Strategic fit:**
- If openclaw/moltbook are popular with a different user base (e.g., visual/no-code agents), we gain distribution
- If they compete with us (building their own payments/escrow), don't integrate — compete
- Decision: integrate only if their product is **adjacent**, not **overlapping**

**Recommendation:** author outreach plan with specific "yes/no integrate" criteria based on their product surface. Human decision required.

---

## 7. CMO Action Checklist (Priority-Ordered)

### This Week (P0)
- [ ] Write AGENTS.md, SKILL.md, SDK READMEs
- [ ] Fix pyproject.toml + package.json metadata
- [ ] Publish a2a-sdk to PyPI
- [ ] Publish @a2a/sdk to npm
- [ ] Publish Docker image
- [ ] Implement /.well-known/agent-card.json
- [ ] Create MCP server.json + publish to registry
- [ ] Add GitHub topics
- [ ] Submit to mcp.so, Glama, PulseMCP, Smithery

### Next 2 Weeks (P1)
- [ ] Launch Show HN post
- [ ] Submit awesome-mcp-servers PR
- [ ] Publish 3 technical blog posts
- [ ] Create LangChain wrapper package
- [ ] Implement referral program (pricing update)
- [ ] Add `team_monthly` pricing tier
- [ ] Add agent support MCP tool
- [ ] Design SLO-based alerts

### Month 2 (P2)
- [ ] Launch `a2a-humans` private beta (5 customers, 10 executors)
- [ ] Add Coinbase Commerce integration
- [ ] Launch status page (status.greenhelix.net)
- [ ] Submit to HuggingFace Spaces, Vercel registry
- [ ] Partner outreach: Stripe, Coinbase, Linux Foundation A2A

### Month 3+ (P3)
- [ ] Launch `a2a-humans` public
- [ ] Content engine: 3 blog posts/week, 1 podcast pitch/week
- [ ] Product Hunt launch
- [ ] Conference sponsorships (if budget)

---

## 8. Success Metrics (30/60/90)

**30 days:**
- PyPI downloads: 100+
- npm downloads: 100+
- Docker pulls: 50+
- MCP registry listing active
- 25 new signups from distribution
- 3 paying customers

**60 days:**
- PyPI downloads: 1,000+
- 100 new signups
- 10 paying customers
- a2a-humans MVP shipped
- $1K MRR

**90 days:**
- PyPI downloads: 5,000+
- 500 new signups
- 50 paying customers
- a2a-humans: 3 active customer agents, 10 human executors
- $5K MRR

---

*Generated by autonomous CMO session against `main` @ b820527 on 2026-04-05.*
