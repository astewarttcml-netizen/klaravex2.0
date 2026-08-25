# DECK-SPEC — Klaravex pitch deck suite rebuild (2026-08-24)

Anthony's verdict on the v1 generated decks in this directory: **"these are all
crap"** — both design and content. This spec defines the rebuild. The v1 files
(`0*-*.pptx`) and generators (`build_decks*.py`) are reference-only; do not
extend them, replace them.

## Deliverables

Six decks, one per audience, in `/home/anthony/klaravex/decks-2026-08-24/v2/`:

| # | File | Audience | Voice rules |
|---|------|----------|-------------|
| 00 | `investor-overview` | Investors | External: corporate voice, no "Loki", no vendor names (Hetzner/Azure/Atera/Vapi/Smartlead/Apollo), concrete numbers |
| 01 | `b2b-sales` | B2B prospects (law/accounting/medical SMBs) | External (same rules) + CTA to klaravex.com |
| 02 | `consumer` | personal.klaravex.com partners/press | External + CTA to personal.klaravex.com; AI always labeled; $29 session / $29 Solo / $39 Family / free scam recovery |
| 03 | `growth-os` | Internal | Internal naming allowed; mark INTERNAL |
| 04 | `klaravex-os` | Internal | Internal; distinguish KLARAVEX-OS (:4100 cockpit) from Founders OS (client portal) |
| 05 | `technical-architecture` | Technical diligence | Internal; ground in ARCHITECTURE.md / Klaravex2.0/MIGRATION.md / klaravex-os README |

## Content standard (what made v1 fail)

- **Pitch narrative, not doc dump.** One idea per slide. A slide is a claim,
  not a list. Max ~25 words of body per slide outside of diagrams/tables.
- Investor arc: cold-open hook → problem → why now → product (two surfaces,
  one engine) → how it works (diagram) → business model → unit economics →
  moat (company runs on its own product) → GTM → traction `[PLACEHOLDER — pull
  real numbers from scorecards; NEVER fabricate]` → team → ask.
- Sales arc (01): pain → what you get → how a ticket flows (diagram) → tiers →
  proof (Secure Score 32→78 in <60 days; weekend network replacement) → free
  assessment CTA.
- Every external claim must trace to repo ground truth (CLAUDE.md, brand/,
  ARCHITECTURE.md, live site copy). No invented TAM, no invented traction.

## Design standard

- Brand: indigo #4F46E5 / violet #7C3AED gradient accents, near-black #1C1C1A,
  warm neutrals #F5F3EE. Logos: `brand/exports/klaravex-logo-{dark,light}-2x.png`,
  icon `klaravex-icon-transparent-400.png`. Fonts: Syne (display) / Inter
  (body); fall back to Noto Sans when unavailable in the render environment.
- 16:9, full-bleed backgrounds (no white-with-a-stripe), consistent grid,
  generous whitespace, big display numerals for stats.
- Real diagrams built from shapes (rounded cards + connectors), not ASCII or
  bullets: the ticket flow, the four-layer Growth OS (A/B/C/D), and the estate
  map (klaravex ↔ Klaravex2.0 ↔ KLARAVEX-OS) each get a designed diagram slide.
- Logo on cover + closing slide of every deck; INTERNAL watermark on 03–05.

## Verification (acceptance criteria)

1. Each deck renders via `soffice --headless --convert-to pdf` with no text
   overflow, no wrapped stat numerals, no overlapping shapes (visually check
   the PDFs page by page).
2. External decks (00–02) pass the banned-phrase/voice grep: no Loki, no
   vendor names, no "I/me/my", no fake metrics.
3. Prices match live: B2B $75–250/user/mo tiers; consumer $29/$29/$39/free.
4. Generator scripts committed alongside output so a copy edit is a re-run.
5. Log a note_submissions row on completion.
