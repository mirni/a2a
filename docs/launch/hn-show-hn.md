# Hacker News "Show HN" — Launch Post

**Status:** Draft — post AFTER A1-A7 Sprint 1 items ship.
**Target posting time:** Tuesday or Wednesday, 14:00 UTC (09:00 ET).
**Avoid:** Fridays, weekends, major holidays, days with big product launches.

---

## Title (max 80 chars — HN truncates longer)

```
Show HN: An MCP server for agent commerce – payments, escrow, reputation
```

**Alternatives (if we want to A/B):**
- `Show HN: Green Helix – MCP server + SDK for agent-to-agent commerce`
- `Show HN: 141 commerce tools as an MCP server for AI agents`
- `Show HN: Formal verification + escrow for AI agents (MCP)`

**Chosen tone:** per H2.4 — technical framing ("MCP server for 141
commerce tools"), not marketing framing ("Stripe for agents").

---

## URL field

`https://github.com/mirni/a2a`

(Must be a direct repo link — HN ranks `Show HN` posts with a product URL
higher than text-only posts.)

---

## Post body (~260 words)

```
Green Helix is an open-source commerce gateway that exposes 141 tools —
billing, payments, escrow, reputation, marketplace, identity, messaging,
disputes — as a single MCP server. It's what I wish existed when I started
building agents last year.

The gateway is a FastAPI service with nine SQLite-backed product modules
(Python-only, no Redis, no Postgres required for local dev). It speaks
MCP (stdio and streamable HTTP), the A2A Protocol (agent-card.json at
.well-known), and plain HTTPS + OpenAPI 3.1. Dual SDKs in Python and
TypeScript, and a one-line install in Claude Desktop / Cursor / Claude
Code:

  pip install a2a-mcp-server

or for TS:

  npx -y @greenhelix/mcp-server

Non-obvious things it does:
  * Performance-gated escrow — funds release only when SLA metrics are hit
  * Ed25519 cryptographic identity with a verifiable claim chain
  * Composite trust scoring on time-series metrics
  * Formal verification of agent properties via Z3 (our "Gatekeeper"
    service) — prove an agent can't overspend, or can only touch whitelisted
    tools
  * End-to-end encrypted agent messaging (X25519 + AES-GCM)
  * Split payments, subscriptions, budget caps, volume discounts
  * Stripe Checkout for fiat-to-credits, 500 free credits on signup

Live sandbox: https://sandbox.greenhelix.net (no signup for read-only)
Live API: https://api.greenhelix.net
Docs: https://api.greenhelix.net/docs (Swagger)
Agent card: https://api.greenhelix.net/.well-known/agent.json

I'd love honest feedback on:
  1. Does 141 tools feel like too many for one MCP server, or is that
     table-stakes for a commerce layer?
  2. Is formal verification something you'd actually use, or is it
     interesting-in-theory-but-never-in-practice?
  3. Anyone shipping agent marketplaces? I'm desperate for
     early-production stories.

MIT licensed.
```

---

## Response strategy (first 2 hours are critical)

1. **Be in the thread.** Comments in the first 60 minutes get 10x more
   visibility. Answer every comment promptly and technically.
2. **Don't argue.** If someone criticises the architecture, thank them and
   either (a) acknowledge the trade-off or (b) explain the reason *once*.
   Never a second time.
3. **Link to evidence.** If someone asks "does it really do X?", link to
   the exact file/line on GitHub. HN respects receipts.
4. **Don't plug the paid tier.** 500 free credits is already in the post;
   pricing comes up only if asked.
5. **Don't vote-manipulate.** HN will detect and flag. One genuine upvote
   from actual users beats 100 from a botnet.

## Responses to expected questions

| Expected question | Canonical answer |
|-------------------|------------------|
| "Why not just use Stripe directly?" | Stripe handles human → merchant. Green Helix handles agent ↔ agent, with reputation, escrow, and verification primitives Stripe doesn't ship. We *use* Stripe for the fiat on-ramp. |
| "Isn't this over-engineered?" | Every individual piece is table-stakes for commerce in the physical world (escrow, reputation, disputes). The question is whether agents need it yet. I think yes; you may disagree — that's fair. |
| "141 tools seems like a lot." | Happy to slim down. Each tool maps to a real operation (e.g., `create_intent`, `capture_intent`, `refund_intent` are three tools because they're three state transitions with different permissions). What's your cut? |
| "How is this different from [X]?" | Genuinely don't know about half the competing projects. Please share links; I'll study them. |
| "Z3 for agent verification — gimmick?" | Maybe. Try `POST /v1/gatekeeper/jobs` with a property like "total_spent ≤ budget"; it'll actually run Z3 and return a proof hash. If it's a gimmick, it's a working one. |
| "Can I self-host?" | Yes. `docker run -p 8000:8000 greenhelix/a2a-gateway:latest` boots the whole thing with SQLite. See repo README. |
| "Licensing?" | MIT. No CLA. |

## Follow-up after the post lands

- If the post gains traction: tweet a screenshot of the HN post from the
  @greenhelix account with a self-deprecating caption.
- Submit to r/LocalLLaMA, r/LLMDevs, r/AI_Agents **24 hours after** the HN
  post, not before. Mention "saw this on HN" is **not** a good intro —
  paraphrase.
- Dev.to tutorial series (A13) should go live within 48h of HN post.
- Reach out to Latent Space, TWIML, MLOps Community podcasts with a polite
  pitch referencing the HN post.

## Pre-launch checklist

- [ ] A1-A7 all shipped and tested
- [ ] Sandbox is green (run smoke test)
- [ ] Repo README has a clear 30-second quickstart
- [ ] Repo has badges (CI, PyPI, npm, Docker pulls, MCP registry)
- [ ] GitHub Issues is enabled with issue templates
- [ ] `/.well-known/llms.txt` and `llms-full.txt` are served
- [ ] You're logged into HN with karma ≥ 1 (or use a higher-karma account)
- [ ] Laptop charged, coffee brewed, 2 hours of uninterrupted time
