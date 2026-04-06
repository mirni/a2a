# Publish & Submit Todo List

Items that require human accounts, external service registration, or package publishing.
Do NOT execute these yet — they are staged for when the human is ready.

## Package Publishing

- [ ] **Publish a2a-sdk to PyPI** — `python -m build && twine upload dist/*` (needs PyPI account + API token)
- [ ] **Publish @greenhelix/sdk to npm** — `npm publish --access public` (needs npm @greenhelix org)
- [ ] **Publish Docker image** — `docker build -t greenhelix/a2a-gateway:0.9.1 . && docker push` (needs Docker Hub greenhelix org)

## MCP Registry Submissions

- [ ] **Official MCP Registry** — `mcp-publisher publish` with namespace `io.github.mirni` (needs GitHub OAuth verification)
- [ ] **mcp.so** — Submit via GitHub issue (name, description, features)
- [ ] **Glama** — "Add Server" button on glama.ai (quality review)
- [ ] **PulseMCP** — Web form at pulsemcp.com/servers
- [ ] **Smithery.ai** — `npm install -g @smithery/cli && smithery mcp publish`
- [ ] **awesome-mcp-servers** — GitHub PR to modelcontextprotocol/servers repo

## A2A Protocol Registration

- [ ] **a2aregistry.org** — Register agent card (needs /.well-known/agent-card.json live)
- [ ] **a2a.ac** — Register on A2A directory
- [ ] **a2a-registry.org** — Register with DNS verification

## skills.sh

- [ ] **Register on skills.sh** — `npx skills publish` (needs SKILL.md in repo)

## GitHub

- [ ] **Add repository topics** — Settings > Topics: `ai-agents`, `mcp`, `mcp-servers`, `a2a`, `agent-commerce`, `agent-payments`, `escrow`, `trust-scoring`, `developer-tools`, `python`, `typescript`

## Awesome Lists

- [ ] **awesome-ai-agents** — GitHub PR to kyrolabs/awesome-agents
- [ ] **awesome-ai-agents-2026** — GitHub PR to caramaschiHG/awesome-ai-agents-2026

## Framework Integrations (Publish)

- [ ] **LangChain** — Submit PR to langchain-community (after langchain-a2a package created)
- [ ] **Vercel AI SDK Registry** — Submit to ai-sdk-agents.vercel.app

## Launch

- [ ] **Hacker News Show HN** — "Show HN: Stripe for AI Agents — 128-tool commerce gateway" (after all P0 done)
- [ ] **Product Hunt** — Launch in "AI Agents" category (4-6 weeks after HN)
- [ ] **AI Agent Store** — Free listing at aiagentstore.ai
- [ ] **AI Agents Directory** — Free listing at aiagentsdirectory.com

## Human Decisions Resolved

- npm org: `@greenhelix`
- Docker Hub org: `greenhelix`
- License: MIT (keep)
- Pricing changes: Defer
- HN timing: Later

## Completed
- **Date**: 2026-04-06
- **Status**: Reviewed by agent. All items are human-only actions requiring external accounts/service registrations. No automation possible.
- **Pre-requisites done**: GitHub topics already set (13 topics), SKILL.md exists in repo.
- **Remaining**: All checklist items require human credentials (PyPI, npm, Docker Hub, MCP registries, etc.).
