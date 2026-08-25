# Master Action Plan — Consumer Line + Klara Workstream
**Sequenced, with owners, dependencies, and critical path. Merge into TASKS.md.**

**Status:** Planning artifact. Decisions #1 (klaravex.com → Option C, Freiberufler) and #2 (beachhead → Berlin/DE) are made. Everything below is execution.

## Owners
- **A** = Anthony (decisions, site/content deploy, account creation, legal publishing)
- **L** = Loki `/do` session (backend/infra builds; per-action Hetzner approval)
- **C** = Counsel / Steuerberater (legal review)

## Critical path to consumer launch (do in this order)
```
[A] Deploy personal.klaravex.com (DE+EN content, working contact)
        │
        ▼
[A+C] Publish Impressum + DSGVO remote-access notice + fix 555 phone
        │
        ▼
[A] Post GBP (service-area) + Kleinanzeigen listing  (disclosure in ad text)
        │
        ▼
[A] Seed 5–10 reviews  →  [A] Log every case from day one
        │
        ▼
[L] Graduate first Green category  →  pass savings / raise automation
```
**Nothing German goes live to ads until the Impressum/DSGVO + deployed site are up.** That's the gate.

## Sequenced tasks

| # | Task | Owner | Blocked by | Notes / source doc |
|---|---|---|---|---|
| 3 | Start the case log (day one) | A | — | Tracker xlsx. Feeds pricing + graduation. Begin with first real case. |
| 7 | Fix live site defects | A | — | 555 phone, Impressum/Datenschutz links, deploy-or-remove empty .de, AI line in ad copy. |
| 6 | Publish Impressum + DSGVO + disclosure | A, C | — (entity decided) | Doc #4. Steuerberater confirms VAT line; counsel reviews before publish. |
| 7b | Deploy personal.klaravex.com (DE+EN) | A | 6 | Doc #7 copy. German default + EN toggle + hreflang. |
| 5 | Post GBP + Kleinanzeigen (Berlin/DE) | A | 6, 7b | Doc #5 channel copy. Then seed reviews. |
| 4 | Phase-1 auto-documentation assist | L | — | Doc #6 brief. Run via `/do`. Read-only discovery first; approval gate on deploy. |
| 10 | Klara language-matching | L | 4 (same pass) | Doc #6 add-on. Locale param → backend language pin. |
| 8 | Atera→Loki retention loop | L | clients live | Doc #3 spec. Phase A→B→C; Green-only autonomy post-graduation. |
| 9 | Rebuild klaravex.com (Option C) | A | coexistence decision | Strip IT Experts Berlin refs. **Open: how it divides from klaravex.com.** |

## Parallel tracks (independent of the consumer critical path)
- **Loki/Klara build (#4, #10)** via `/do` — can start now; doesn't block the website launch.
- **klaravex.com B2B rebuild (#9)** — gated on the coexistence decision, not on consumer launch.

## Open decisions still on Anthony
1. **klaravex.com ↔ klaravex.com coexistence** — how two German B2B sites divide (blocks #9).
2. **personal.klaravex.com** — park → .de EN, or hold as future US consumer site.
3. **Consumer pricing numbers** — confirm the proposed €-tiers before publish.
4. **VAT status** — USt-IdNr vs. §19 Kleinunternehmer (Steuerberater).

## Definition of "launched" (consumer beachhead)
- personal.klaravex.com live, bilingual, compliant (Impressum + DSGVO), working contact.
- GBP + Kleinanzeigen live with disclosure in copy.
- ≥1 real case logged; review-request flow running.
- Klara responding in the correct language per site.

## How to execute the L tasks
Open Claude Code in the project and run **`/do`** (command now defined at `.claude/commands/do.md`). It reads TASKS.md, takes the next unblocked L task, and enforces note_submissions + per-action Hetzner approval. The orchestrator (this) session does not run those directly.
