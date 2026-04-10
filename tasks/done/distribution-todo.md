# Prompt

## Role
You are a Growth Strategist specializing in the "Agentic Economy" and API-first business models.

## Product Context
I am building Green Helix, a platform providing A2A (Agent-to-Agent) services via API. The goal is to allow autonomous AI agents to discover, interact with, and pay for services without human intervention.

## Goal
Plan the distribution of the services and compile a list of  marketing/distribution related todo items. The goal is to reach as many customers as possible. Focus should be on AI agent customers, but consider humans also.

## Tasks
* Read docs/infra/DISTRIBUTION.md and review the actionable items there. Update the list based on the current state of the product.
* Create a todo list for implementing all integrations, sorted by ROI. We want to reach as many agents as possible.
* Create a feature branch and commit the generated output but do not create PR yet. Human will review locally.
* Identify and prioritize marketing and distribution channels to reach the maximum number of autonomous agents and their developers.

## Output
* Discovery Protocols & Marketplaces: Identify where agents "look" for services (e.g., Model Context Protocol (MCP), LangChain Hub, OpenAI GPT Store, specialized A2A registries).
* Infrastructure Integrations: Recommend 3–5 high-impact integrations with agent frameworks (e.g., CrewAI, AutoGen, LangGraph) or developer environments (e.g., Cursor, Aider).
* The "Agent-SEO" Strategy: How should the API documentation and .well-known files be structured so that LLM-based "planner" agents prioritize Green Helix over competitors?
* ROI Ranking Table: Create a table ranking these channels/integrations based on:
  ** Reach: Potential volume of agent requests.
  ** Ease of Implementation: Engineering effort.
  ** Conversion: Likelihood of the agent successfully completing a transaction.
  ** Overall ROI: High/Medium/Low.
* Detailed action plan for agent:
  ** with items to be implemented (integrations, etc)
  ** any relevant implementation plan details
* Detailed action plan for human:
  ** Any accounts/registrations they need to do to enable integtrations and distribution channels
  ** Any decisions to make about any of the items

## Tone
Analytical, forward-thinking (focus on 2026-2027 trends), and technically precise regarding API standards.

## Completed

**Date:** 2026-04-10
**Branch:** `feat/distribution-plan-2026-04`
**PR:** none (per task instructions — human will review locally)

### Deliverables

- **`docs/infra/AGENT_DISTRIBUTION_STRATEGY_2026-04.md`** — strategic plan
  covering all required output sections:
  - §1 Product state delta vs. v0.5.0 DISTRIBUTION.md
  - §2 Discovery Protocols & Marketplaces (MCP, A2A, agents.json, OpenAPI,
    Agent Commerce Kit, ACP, AGNTCY, ANP + all major registries + IDE
    directories)
  - §3 Top-5 infrastructure integrations (MCP server, LangChain/LangGraph,
    CrewAI, Vercel AI SDK, Cursor/Claude IDE family)
  - §4 Agent-SEO strategy (three-layer ranking model, `.well-known/`
    artefact bundle, tool description template, pricing machine-readability,
    trust signals, name-anchoring)
  - §5 ROI ranking table (25 channels × Reach × Effort × Conversion × ROI)
  - §6 Detailed agent action plan (Sprint 1, 2, 3)
  - §7 Detailed human action plan (accounts, credentials, decisions)
  - §8 Leading + lagging metrics with kill criteria
  - §9 Competitive moat summary
  - Appendix A: Distribution tracker template
  - Appendix B: Protocol bet heat-map 2026-2027

- **`tasks/backlog/distribution-execution-queue.md`** — ROI-sorted implementation
  todo list for engineering agents (A1-A21 across 3 sprints, self-contained,
  ordered by ROI, with acceptance criteria).

- **`docs/infra/DISTRIBUTION.md`** — updated to v0.6.0 with current product
  state (PyPI/npm/Docker all published, agent-card live, integrations
  drafted). Cross-linked to new strategy doc and execution queue.

### Key findings

1. **70%+ of expected reach comes from ~10 zero-cost artefacts** shippable
   in a single ~4.5 engineer-day sprint (MCP server + registry submissions
   + `.well-known/` bundle + tool description rewrite + LangChain/CrewAI
   publish + IDE docs).
2. **MCP is the #1 bet** — one server implementation lights up 10+ client
   runtimes (Claude Desktop, Claude Code, Cursor, Windsurf, OpenAI Agents
   SDK, Google ADK, CrewAI, LangChain MCP adapter, LlamaIndex).
3. **Our formal verification (Z3 Gatekeeper) is a unique moat** — no
   competing A2A platform ships this. Should be surfaced in every registry
   listing and tool description.
4. **Deprioritise** AutoGen/AG2 (Microsoft merger churn), AutoGPT, SuperAGI,
   BabyAGI. Track but don't invest in ACP/AGNTCY/ANP until one breaks out.
5. **Human blockers** — several account registrations and decisions listed
   in strategy doc §7 (~12 accounts, ~10 decisions, ~1 hour total).
