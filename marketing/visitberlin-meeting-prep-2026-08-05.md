# visitBerlin Meeting Prep — Wednesday 2026-08-05

**Contact:** Frank Heise, Deputy Head of Digital & IT
**Coordinator:** Jule Weidner, Advisor to the Executive Board
**Org:** Berlin Tourismus & Kongress GmbH (city/state-owned)
**Team:** CWU AI — 10-person cross-departmental peer-to-peer unit

---

## What They Want

Two flagship projects:

### Project 1: Knowledge Manager
- Central knowledge capture (information, experiences, best practices)
- Accessible to the whole organization
- **This is a RAG/KB system.** You built exactly this for Klaravex (88-chunk KB, `/api/v1/chat/message`, cited answers, reindex pipeline).

### Project 2: Customer Journey Chatbot
- Evolution of their existing "Berlin Bot"
- Full visitor lifecycle: inspiration -> booking -> in-Berlin -> departure
- **This is a context-aware chat widget + multi-intent routing system.** You built Loki chat widget (per-locale, quickReply, AbortController, dedup) and the 8-assistant Vapi voice squad.

---

## Their AI Stack (3-Level Model)

| Level | Tool | Purpose |
|---|---|---|
| 1 — Free | Microsoft Copilot | Research, quick questions (all staff) |
| 2 — Specialized | Dept-purchased tools | Image, video, etc. |
| 3 — Protected | Internal server (`ai.visitberlin.de`) | Confidential data, custom bots |
| Pilot | Claude (Anthropic) | Testing with CWU AI + executives |

**Key insight:** They already run an internal AI server AND are testing Claude. You have deep expertise in both local AI deployment (Ollama, qwen, local whisper) and Claude (you build on it daily). This is rare — most consultants know one or the other.

---

## Constraints to Navigate

### Public Procurement (>EUR 1,000 = tender)
- Services above EUR 1,000 must be publicly tendered
- Large agencies typically win tenders
- Frank is explicitly telling you this is a barrier and looking for a workaround

### Engagement structures that could work under EUR 1,000/engagement:
1. **Modular micro-consulting** — scoped discovery sessions, architecture reviews, or workshops each under EUR 1,000
2. **Knowledge transfer / training** — CWU AI team upskilling (per-session billing)
3. **Proof-of-concept builds** — deliver working prototypes that inform their tender specs
4. **Tender advisory** — help them write the technical requirements for their public tender (you shape the spec, then they tender it — you may or may not bid)
5. **Framework agreement** — if they can establish a consulting framework, individual call-offs under EUR 1,000 work without re-tendering (ask Frank about this)

### GDPR / Data Protection
- Non-negotiable for a public org
- Your local AI stack (Ollama on bare metal, no data leaving the network) is a strong differentiator here
- `ai.visitberlin.de` shows they already think this way — you speak their language

### Public Accountability / Transparency
- Everything you build may be subject to public scrutiny
- Open-source tooling, auditable architectures, documented decision-making

---

## Your Differentiators for This Meeting

1. **You've already built both projects they want.** Knowledge Manager = your KB pipeline. Customer Journey Chatbot = your Loki widget + Vapi voice routing. You can demo real production systems, not slides.

2. **Local AI + cloud hybrid.** You run qwen-72b on bare metal with an RTX 3090, Ollama, LiteLLM proxy — AND you orchestrate Claude for complex tasks. Their Level 3 (internal AI server) aligns perfectly with your architecture.

3. **Claude expertise.** They're testing Claude right now. You're one of the most intensive Claude users in Berlin (Claude Code as your daily development environment, agent orchestration, multi-model routing).

4. **GDPR-by-architecture.** Your local-first approach means confidential data never leaves the building. For a public org this isn't a feature — it's a requirement.

5. **One-person operator model.** You're not an agency charging EUR 200/hr with 5 layers of project management. You're the person who builds AND advises. For a 10-person peer-to-peer team, this is a cultural fit.

---

## Questions to Ask Frank / The Team

### About the Knowledge Manager
- What content sources exist today? (SharePoint, file shares, wikis, Confluence, email archives?)
- What's the current search/discovery pain? (People can't find things? Information is siloed by department?)
- How many documents / what volume of knowledge?
- Is `ai.visitberlin.de` the intended host, or would this be a separate system?
- What's the access model? All 200+ staff? Just CWU AI? Department-gated?

### About the Customer Journey Chatbot
- What does the current Berlin Bot do? What platform is it on?
- What data sources feed it? (event calendars, hotel APIs, transport APIs, visitberlin.com content?)
- Multi-language requirements? (EN/DE minimum, probably more for tourism)
- Integration points? (booking systems, ticket platforms, public transport)

### About the Engagement
- Has Jule Weidner defined a budget envelope for the AI initiatives?
- Is there a framework agreement mechanism that allows sub-EUR 1,000 call-offs without tender?
- What's the timeline? When do they want the Knowledge Manager live?
- Would a paid proof-of-concept (under EUR 1,000) be a valid first step?
- Are they open to you helping write the tender spec for the larger build?

### About Their Infrastructure
- What does the `ai.visitberlin.de` server run? (Ollama? vLLM? Azure OpenAI? Something else?)
- Martin Wobke (Network Admin, AI Server) — is he the technical decision-maker for infra?
- What models are they running locally?
- How is authentication handled for the internal server?

---

## Recommended Meeting Flow

1. **Listen first** (15 min) — Let the team present their current state and pain points. Take notes. Show you're there to understand, not to pitch.

2. **Show, don't tell** (15 min) — Demo your production KB system (live curl to your chat endpoint returning cited answers). Show the Loki chat widget on klaravex.com. If possible, show the local AI stack (Ollama dashboard, LiteLLM routing). Concrete beats conceptual.

3. **Knowledge Manager architecture sketch** (15 min) — Whiteboard a simple architecture: document ingestion -> chunking -> embedding -> vector store -> retrieval-augmented generation -> cited answers. Map it to their `ai.visitberlin.de` infrastructure. Show you can build this on THEIR server, not yours.

4. **Engagement model discussion** (15 min) — Propose a paid discovery workshop (under EUR 1,000) as the first step: audit their content sources, map their knowledge graph, deliver a technical architecture document + cost estimate for the full build. This gives them a procurement-safe entry point.

---

## What NOT to Do

- Don't pitch Klaravex MSP tiers — this isn't a managed IT sale
- Don't mention Klaravex LLC or US entity structure — irrelevant here
- Don't promise to bid on a public tender you might not win — focus on the advisory/consulting angle
- Don't oversell — they're a public org, they smell sales pitches from agencies daily. Be the technical person who actually builds things.
- Don't discuss pricing until you understand scope — listen first

---

## Pricing Guidance (if it comes up)

For reference, NOT to lead with:
- Discovery workshop (1 day): EUR 800 (under tender threshold)
- Architecture review + recommendation doc: EUR 950 (under tender threshold)
- Ongoing advisory retainer: structure as monthly EUR 950 modules
- Full Knowledge Manager build: this would require a tender — help them write the spec, then decide whether to bid

---

## Key People to Connect With

| Person | Why |
|---|---|
| **Frank Heise** | Your primary contact. Deputy Head Digital & IT. Technical decision influencer. |
| **Jule Weidner** | Coordinator + Advisor to Executive Board. Budget authority. Not in CWU AI team list but runs it. |
| **Martin Wobke** | Runs `ai.visitberlin.de`. Your technical counterpart for infrastructure. |
| **Kerstin Block** | Business Development + leads CWU Future Hub. Strategic alignment. |
| **Katharina Mohrl** | Comms Team Lead. Key stakeholder for Knowledge Manager content. |

---

## One-Line Positioning

"I build production AI systems — knowledge bases, chat interfaces, voice assistants — on local infrastructure that keeps your data in-house. I've already built both of the systems you're planning."
