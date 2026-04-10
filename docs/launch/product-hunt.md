# Product Hunt Launch — Green Helix

**Status:** Draft — post AFTER A1-A7 Sprint 1 items ship, ideally **2
weeks after the Hacker News launch** (the HN crowd and PH crowd overlap
only 10-15%, but spacing them gives each launch its own news cycle).

**Category:** AI Agents (per H2.5 decision)
**Target day:** Tuesday, 00:01 PST (Pacific time).
**Prep window:** 4-6 weeks before launch day.

---

## Name

```
Green Helix
```

## Tagline (≤60 chars)

```
The commerce layer for AI agents — MCP-native
```

**Alternatives:**
- `141 commerce tools for AI agents — MCP + A2A`
- `Pay, escrow, and verify AI agent transactions`
- `Stripe-for-agents: payments, escrow, reputation`

## Description (≤260 chars)

```
Open-source commerce gateway for AI agents. 141 tools — payments, escrow,
reputation, marketplace, identity — as one MCP server. Works with Claude,
Cursor, LangChain, CrewAI. 500 free credits on signup. MIT licensed.
```

## Topics

- AI Agents
- Developer Tools
- APIs
- Open Source

## Gallery (media requirements)

Product Hunt shows up to 6 media slots. Provide:

1. **Cover image** (1270×760 PNG): architecture diagram — agent → MCP →
   gateway → [billing, payments, escrow, reputation, marketplace]. Dark
   background with Green Helix green accent.
2. **Screenshot 1**: Claude Desktop with the Green Helix MCP server loaded,
   showing `pay_agent` being called from a conversation.
3. **Screenshot 2**: Swagger UI at `api.greenhelix.net/docs` showing the
   141-tool surface.
4. **Screenshot 3**: The marketplace dashboard at `greenhelix.net`
   listing registered agents with trust scores.
5. **GIF** (≤5 MB): 15-second demo of `pip install a2a-mcp-server` →
   `claude_desktop_config.json` edit → Claude using the `create_escrow`
   tool successfully.
6. **GIF**: 10-second demo of two CrewAI agents negotiating a price via
   `a2a-crewai` toolset.

## Links

- **Website:** https://greenhelix.net
- **Sandbox:** https://sandbox.greenhelix.net
- **GitHub:** https://github.com/mirni/a2a
- **Docs:** https://api.greenhelix.net/docs
- **Twitter/X:** @greenhelix (create if not exists)
- **Discord:** https://discord.gg/greenhelix (create if not exists)

## Maker comment (first comment, pinned)

```
Hey Product Hunt 👋

Maker here. Green Helix started as a side-project answer to a specific
question: when two AI agents need to transact with each other, where does
the money and the trust live?

The obvious answer — "use Stripe" — works for agent → merchant, but not
agent ↔ agent. You need escrow (agent A deposits, agent B only gets paid
if it delivers). You need reputation (agent A refuses to buy from an
agent with a low trust score). You need identity (who signed this
transaction cryptographically). And increasingly, you need formal
verification (prove the agent *can't* overspend before it runs).

We built all of that as one MCP server with 141 tools. It runs locally
with `pip install a2a-mcp-server`, or you can hit the hosted gateway at
api.greenhelix.net. Free tier is 500 credits + 100 req/hr, no credit
card required.

What's in there today:
• Full commerce stack — payments, escrow, subscriptions, split payments
• Cryptographic identity (Ed25519) + composite trust scoring
• End-to-end encrypted agent messaging (X25519/AES-GCM)
• Performance-gated escrow (funds release only when SLA metrics hit)
• Formal verification of agent properties via Z3 ("Gatekeeper")
• Pre-built MCP integrations for Claude Desktop, Cursor, Claude Code,
  Windsurf
• LangChain, CrewAI, Vercel AI SDK tool packs
• Stripe Checkout for fiat → credits
• Dispute resolution state machine with 7-day deadlines

What's not in there:
• A polished UI for non-developers (we're API-first; contributors
  welcome)
• Production-grade audit logging to an external SIEM (planned Q3)
• On-chain settlement (we're protocol-agnostic; happy to discuss)

I'd love your feedback — especially if you're building agent
marketplaces, multi-agent crews, or any kind of AI workflow where two
non-human actors need to transact. What would you want us to build next?

— Mirni (maker)
```

## Response strategy

1. **Be online all day.** Product Hunt launches are a 12-hour sprint.
   Respond to every comment within 30 minutes for the first 4 hours, then
   every 2 hours for the rest of the day.
2. **Thank every upvoter** whose name you recognise (via DM if possible).
3. **Don't ask for upvotes.** Product Hunt de-ranks posts with obvious
   vote solicitation. Instead, ask people to try the sandbox and share
   feedback.
4. **Share the PH URL on Twitter/X** once — in the morning of launch day
   — with a short thread explaining the project. Don't repost.
5. **Engage with other makers launching the same day.** Upvote and
   comment on 5-10 other launches; the reciprocity effect is real.

## Pre-launch checklist (4 weeks before)

- [ ] Identify a hunter with ≥5K followers (search PH Makers page; DM
      3-5 hunters with a 100-word pitch)
- [ ] Create Product Hunt account with bio, avatar, verified email
- [ ] Build a "ship" page on greenhelix.net explaining the launch day
- [ ] Email your waitlist (if any) 1 week before launch: "We're
      launching on PH next Tuesday, would love your support"
- [ ] Prepare all gallery media (screenshots, 2 GIFs, cover)
- [ ] Schedule tweets + LinkedIn posts for launch morning (00:01 PT,
      06:00 PT, 12:00 PT, 18:00 PT)
- [ ] Queue 3 dev.to tutorials to auto-publish on launch day
- [ ] Alert relevant Discord/Slack communities (LangChain, CrewAI, MCP)
      **the day of**, not before. No spam.

## Pre-launch checklist (day before)

- [ ] Sandbox is green (`scripts/ci/integration_smoke.py`)
- [ ] PyPI + npm versions match; docker image `:latest` tag works
- [ ] One-click Claude Desktop install button tested
- [ ] Rate limits set to handle a 10x traffic spike
- [ ] `/v1/health` returns 200 and reports all 10 DBs
- [ ] Backup of all databases taken
- [ ] On-call laptop charged, coffee brewed, 12 hours cleared

## Post-launch

- Write a retrospective blog post within 48 hours: "What we learned
  launching on Product Hunt"
- Add launch stats to `reports/distribution-tracker.md`
- If top 10 in category: screenshot + tweet + LinkedIn post
- If top 5 overall: email your waitlist with a thank-you + results
