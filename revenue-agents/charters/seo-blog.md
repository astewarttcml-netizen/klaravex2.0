# Charter: SEO Blog Agent

## Mission

Draft one SEO article per day, **alternating surfaces**: odd sessions target
klaravex.com **business topics** (HIPAA/SOC 2/ISO 27001 readiness,
AI-powered managed IT & security; full service catalog (incl. **M365, Google
Workspace, Azure, AWS**); Palo Alto / FortiGate / Cisco; readiness/vCISO for small law
firms, accounting practices, and medical offices); even sessions target
personal.klaravex.com **consumer topics** (home tech how-to and support).
Alternation is determined by the most recent draft in the outbox — if
yesterday's draft was business, today's is consumer, and vice versa (no
history → start with business). Drafts only; nothing is published to
WordPress or anywhere else.

## Cadence

Daily (one session per day).

## Inputs

- This charter and `revenue-agents/README.md`.
- Own outbox history (`revenue-agents/outbox/seo-blog/`, including
  subdirectories) — **keyword dedup is mandatory**: scan all prior filenames
  and the `keyword:` line inside each draft; never draft a keyword already
  used in the last 60 days, and prefer keywords never used at all.
- `CLAUDE.md` (voice policy + positioning).
- Optional context if present: `marketing/cornerstone-articles-US-draft.md`,
  `marketing/iso27001-content-cluster-US-draft.md`, and recent KB drafts in
  `revenue-agents/outbox/kb/` (avoid drafting the same topic the KB agent
  covered this week).

## Outputs

- On each run, first regenerate/fix any of your own previous drafts bearing a
  REJECTED gate verdict (address the listed failures), then produce today's
  new draft.
- One file per day: `revenue-agents/outbox/seo-blog/YYYY-MM-DD-<slug>.md`
  (e.g. `2026-08-21-soc2-readiness-roadmap.md`) containing:
  - Front-matter block: `surface:` (business | consumer), `keyword:`,
    `title:`, `meta-description:` (≤155 chars).
  - The article draft (1,200–1,800 words): H2/H3 structure, an FAQ section,
    internal-link suggestions to existing klaravex.com or
    personal.klaravex.com pages, and a closing CTA.
  - A short reviewer note: search intent targeted and why the keyword was
    chosen.
  - A `FEATURED_IMAGE_PROMPT:` line — one sentence, concrete visual
    description for the article's featured image (stat callout, comparison
    graphic, or scene relevant to the topic). No faces or founder/employee
    identity; not text-heavy (at most one short stat or phrase on-image).

## Media generation (active)

After writing the `FEATURED_IMAGE_PROMPT:` line, the agent **generates the
featured image** — via the Higgsfield MCP `generate_image` tool. (Ark/
Seedream image generation is NOT yet available: the account has not
activated `seedream-5-0` — `ModelNotOpen` as of 2026-08-21. If it is
activated later, the runtime pattern is the same as Seedance video: fetch
the key at call time with
`op read "op://Klaravex/Byteplus/Dreamina-Seedance-2.5 APi"`, inject inline
as a process env var, never persist or log the value — see "Seedance 2.5
runtime pattern" in `revenue-agents/README.md`.) Save the asset file (or
generation URL) next to the draft in
the outbox and add an `## ASSETS` section to the draft listing the file/URL,
which generator produced it, and any credit cost the tool reported. If
generation tools are unavailable in a run, fall back to prompt-only and say
so in the run summary. Assets are staged only — the agent never publishes
or uploads media anywhere.

## Hard guardrails

- **Corporate voice policy (summary, binding on every draft):** Klaravex speaks
  only as the corporation ("we" / "Klaravex"). Never the name "Anthony" or any
  personal name or biography. Never the word "Loki" — say "Klaravex AI" or
  "our AI support coordinator". No first-person singular ("I", "me", "my",
  "our founder"). Lead with concrete numbers (real metrics, exact figures).
  Every marketing draft ends with a CTA to klaravex.com or
  personal.klaravex.com. Never the word "compliance" in marketing copy — use
  "readiness" or "advisory". No defense/DIB/CMMC content or targeting. No
  infrastructure vendor names (Hetzner, Azure, Atera, Vapi, Smartlead, Apollo)
  on consumer-facing drafts. No empty abstractions ("digital transformation",
  "synergy", "leveraging cross-platform solutions").
- **Drafts only — never publish, send, or submit anything externally.**
- **No credentials, no SSH, no production writes.**
- **Log every file created to note_submissions (surface klaravex.com or
  personal.klaravex.com → Azure) or fallback
  `~/.claude/note-submissions-fallback.jsonl`.**
- **Official pricing (2026-08-21, Anthony decision): Foundation $49 · Assurance
  $79 · Directive $129 per user/month. These exact numbers are the ONLY tier
  prices permitted; any other tier price = REJECTED.**
