# Build status

**Updated:** 2026-06-27
**Session:** loki/session-1782538253-27386

## Deliverables

| Folder | Artifact | Status | Bytes |
| --- | --- | --- | --- |
| `proposal/` | `proposal.md` | ✓ complete | 24,625 |
| `architecture/` | `architecture.md` | ✓ complete | 26,206 |
| `architecture/` | `data-flow.md` | ✓ complete | 11,177 |
| `architecture/adr/` | 9 ADRs (adr-0001 … adr-0009) | ✓ complete | ~24,700 total |
| `compliance/` | `dpia.md` | ✓ complete | 16,148 |
| `compliance/` | `gdpr-dossier.md` | ✓ complete | 12,045 |
| `compliance/` | `nis2.md` | ✓ complete | 9,047 |
| `compliance/` | `bsi-c5.md` | ✓ complete | 14,011 |
| `compliance/` | `data-residency.md` | ✓ complete | 7,317 |
| `mockup/` | `index.html` (7 screens, persona switcher) | ✓ complete | 62,194 |
| `pitch-deck/` | `deck.html` (16 slides) | ✓ complete | 39,463 |
| `assets/` | placeholder | empty by design — diagrams inlined as SVG/mermaid | — |
| `_source/` | `visitberlin-concept-v0.1.md` | (input, unchanged) | 13,783 |

**Total bundle:** ~247 KB.

## Coverage map (PRD → artifact)

| Concept § | Topic | Addressed in |
| --- | --- | --- |
| §1 Background & objectives | proposal §0, §1, §2 |
| §2 Push/Pull/AI | proposal §2, §4.5; architecture §3.3 |
| §3.1 Sources | proposal §4.1, §6.7; architecture §3.1, §7; ADR-0003, ADR-0007 |
| §3.2 Profile | proposal §4.2; architecture §5.1, §7.4 |
| §3.3 Subscriptions | proposal §4.3; mockup profile screen |
| §3.4 Frequency | proposal §4.4, §6.8; architecture §4.3 |
| §3.5 Bot | proposal §4.5, §6.1, §6.9; architecture §3.3, §4.2; ADR-0002, ADR-0008; mockup bot screen |
| §4 Permission model | proposal §4.6; architecture §5; ADR-0002, ADR-0006 |
| §5 Lifecycle | proposal §4.7, §6.5; architecture §3.4; data-flow C |
| §6 Recommended functions | proposal §4.8, §6.4; architecture §3.2, §4 |
| §7 Data protection | proposal §4.9, §6.2, §6.3, §6.7; all compliance docs |
| §8 Open points | proposal §6 (all 8 named with recommended resolutions) |

## Unresolved-point resolutions (proposal §6)

| # | Concept point | Resolution doc |
| --- | --- | --- |
| 6.1 | "labelled or excluded" Review-due | proposal §6.1; architecture §3.3 |
| 6.2 | prompt-injection defence | proposal §6.2; architecture §3.2 (steps 2, 9) |
| 6.3 | audit log vs no-copy | proposal §6.3; ADR-0004; compliance/dpia.md §3.6 |
| 6.4 | duplicate-detection threshold | proposal §4.8, §6.4 |
| 6.5 | synchronised re-submission wave | proposal §6.5; data-flow C; architecture §3.4 |
| 6.6 | push relevance criteria | proposal §6.6 |
| 6.7 | mailbox scope | proposal §6.7; ADR-0007 |
| 6.8 | bulk-upload notification flood | proposal §6.8; architecture §4.3 |
| 6.9 | bot SLA | proposal §6.9; architecture §3.3 |

## Open follow-ups

- Commercial annex (pricing) — outside this autonomous build; produced separately with Klaravex commercial team.
- German translation of proposal and pitch deck — phase 0 / 1 activity, by Klaravex localisation.
- Walk-through booking with visitBerlin — sales-team action item.

## Audit trail

Built autonomously in a single Loki session by Claude (claude-opus-4-7) against the visitBerlin concept v0.1 PRD. No external dependencies introduced; no secrets; all artifacts plain Markdown or single-file static HTML.
