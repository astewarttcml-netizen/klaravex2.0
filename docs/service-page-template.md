# Klaravex — B2B Service Page Template
**Version:** 1.0 · 2026-06-03 · Use for all new B2B service pages and rebuilds.
**Source:** `03-Revenue-Launch-Consumer-Pricing-and-Page-Template.md`

Loki fills the bracketed slots. Never reorder sections.

---

```
[H1] — Outcome-first headline (what the client gets, not the tech name)
       e.g. "Microsoft 365, run right — so your email, files, and team just work."

[Intro · 2–3 sentences] — The problem in the client's words + the promise.
       Plain English. No vendor jargon in the first line.

[Section: "What's included"] — 4–6 bullets, each = capability + benefit
       • [Capability] — [why it matters to them]

[Section: "Who this is for"] — 1–2 lines naming the buyer
       e.g. "5–50 person firms with no in-house IT and real uptime needs."

[AI note · 1 line] — How Loki + human escalation applies here.
       "Loki monitors this 24/7 and flags issues instantly — a senior engineer
        acts on anything serious."

[Section: "What good looks like"] — 1 outcome/proof point (US-framed, anonymized)
       e.g. "A 28-user firm migrated in one week, zero data loss."

[FAQ · 3 questions] — the real objections (price model, lock-in, transition risk)

[CTA block] — "[Get a Free IT Assessment →]"  + secondary "[See pricing →]"

[Footer microcopy] — "No vendor commissions, ever. US-based, remote-first."
```

---

## Build rules (enforce on every page)

1. Apply Americanization find-and-replace before publishing:
   - NIS2 / DSGVO / GDPR (as US selling point) → HIPAA / SOC 2 / NIST CSF / CCPA
   - € / EUR → $ / USD
   - Berlin / "on-site in Berlin" → "US-based, remote-first, nationwide"
   - "English-speaking IT in Germany" → delete
   - optimise / centre / organisation / programme → optimize / center / organization / program
   - Impressum / Datenschutz → Privacy Policy / Terms / DPA
   - "compliance" (marketing) → "readiness" / "advisory" / "preparation"

2. Build as **DRAFT** — never live-edit a published page.

3. Use only prices from `02-Content-Drafts.md`. Do not invent numbers.

4. One AI note per page — transparent, never implying Loki is human.

5. US spelling, USD throughout.

6. Every nav link must resolve to a real, published page — no "coming soon."

## Validation gate before publish

Grep the page content for these strings — all must return zero hits:
- `€`
- `NIS2`
- `DSGVO`
- `Berlin`
- `optimise`
- `centre`
- `compliance` (except in "readiness/advisory/preparation" context — check manually)

## Dark theme palette (Gutenberg inline styles)

| Role | Hex |
|------|-----|
| Hero bg | #0D1117 |
| Alt section bg | #111827 |
| Card bg | #161B22 |
| Card border | #1E293B |
| Cyan accent border | #06B6D4 |
| H1/H2 color | #F1F5F9 |
| Body text | #94A3B8 |
| Muted text | #64748B |
| CTA band bg | #06B6D4 |
| CTA button bg | #0D1117 |

## Pages that need this template applied (backlog)

All 14 ported service pages from klaravex.com should eventually be rebuilt
to this structure. Priority order: whichever pages are getting the most traffic
(check analytics once installed).

Current service pages at `/business/services/`:
- microsoft-azure, microsoft-365, intune-endpoint-management
- firewall-network-security, it-security-audit
- aws-cloud, google-workspace, ai-workflow-automation
- (+ remaining ~9 from itexperts port)
