<!--
SPEC — Monthly competitive monitor (US / klaravex.com). The recurring scheduled task is created from this spec.
Prepared 2026-06-23.
-->

# Competitive Monitor — Spec

**Goal:** Keep the US competitive brief current without a full quarterly rebuild — catch material competitor moves monthly, flag what matters, recommend a response.

**Cadence:** Monthly, 1st of the month, 9:00 AM local. Full brief refresh quarterly (manual).

**Scope:** US only (klaravex.com). Do not pull EU/.de competitors into this monitor.

## Watch list & triggers

| Competitor | Watch for | Why it matters |
|---|---|---|
| **Ntiva** | New GRC/compliance service-line content; HIPAA/SOC 2/ISO messaging moving to the lead; new vertical pages; acquisitions | They're formalizing GRC — the clearest threat of moving into Klaravex's lane at scale |
| **Compliancy Group + Healthicity** | Integration progress; move beyond healthcare; new security (not just docs) capabilities | June 2026 acquisition strengthens the #1-vertical incumbent |
| **Coro** | Pricing changes; MDR/human-SOC additions; new compliance depth; major releases | Could close the "platform, not service" gap |
| **Cynomi** | Packaging/pricing changes (restructure in flight); SMB-direct moves; new content velocity | Content/SEO competitor; channel model could shift |
| **Electric** | Compliance features; vertical moves; financial/health signals | Currently no compliance — a reversal would change the map |

## Output format (each run)

A short digest saved to `klaravex/marketing/competitive-monitor/YYYY-MM.md`:
1. **What changed** — bullets per competitor with a source URL; "no material change" is a valid finding.
2. **Why it matters** — one line each, only for material items.
3. **Recommended response** — concrete, only where warranted (e.g., "Ntiva launched an ISO 27001 page — accelerate our ISO cluster").
4. **Watch next month** — anything to track.

Keep it tight: if nothing material changed, say so in a few lines. No filler.

## Routing
US-surface competitor research → Azure `klaravex-db` per project rule. Note in each digest that the note_submissions row is outstanding if no DB write path exists in the run.
