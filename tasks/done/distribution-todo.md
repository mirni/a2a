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

**Date:** 2026-04-02

**Output:**
- `plans/distribution-action-plan.md` — Full action plan with ROI ranking, agent/human task lists, Agent-SEO strategy
- `docs/infra/DISTRIBUTION.md` — Updated to v0.5.0 with current state (sandbox done, website docs done, AGENTS.md/SKILL.md gaps identified, framework stats updated, AG2 deprecated)
- Committed to `feat/distribution-plan` branch (no PR per instructions)
