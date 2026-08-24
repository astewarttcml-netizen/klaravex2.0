# Charter: KB Agent

## Mission

Draft one knowledge-base article per session, **alternating surfaces**:

- **business** — for klaravex.com/knowledge-base/ (IT readiness, M365/GWS/AWS,
  HIPAA/SOC 2 readiness; cloud (**M365, Google Workspace, Azure, AWS**);
  firewalls (Palo Alto/FortiGate/Cisco); UniFi only when LAN-relevant;
  security topics for small law firms,
  accounting practices, and medical offices).
- **consumer** — for personal.klaravex.com (how-to / support topics: Wi-Fi,
  slow computers, account lockouts, phishing, backups).

Surface selection is balance-based: draft for whichever surface has fewer
drafts in the outbox over the last 14 days (ties go to business). Pick a topic
from the pools below that has not been drafted in the last 60 days; if the
whole pool has rotated through, start over. Drafts only; nothing publishes.

## Cadence

Daily (one session per day, seven days a week).

## Topic pools

Wording rule (CLAUDE.md legal warning): marketing copy uses
"readiness"/"advisory" — never "compliance".

### Business (klaravex.com/knowledge-base/)

HIPAA / healthcare IT readiness:
- what HIPAA actually requires of a small medical practice
- HIPAA risk analysis explained for medical offices
- business associate agreements: which vendors need one
- encrypted email for healthcare practices
- telehealth security checklist for small practices

SOC 2 / ISO 27001 readiness:
- SOC 2 readiness roadmap for startups
- SOC 2 Type I vs Type II explained
- ISO 27001 readiness cost for small businesses
- what auditors ask for in a SOC 2 audit
- vendor risk questionnaires: how to answer them fast

M365 / Google Workspace / AWS:
- Microsoft Secure Score explained and how to improve it
- Microsoft 365 vs Google Workspace for small firms
- conditional access policies for small businesses
- M365 backup strategy: what Microsoft does not back up
- AWS security baseline for a small business account
- Intune device enrollment guide for small teams

Managed IT / vertical:
- IT onboarding checklist for a new law firm employee
- what accounting firms need from IT during tax season
- IT disaster recovery plan template for small businesses
- cyber insurance security questionnaire: how to pass it
- MSP vs internal IT cost for a 20-person practice

Network / firewall / UniFi:
- UniFi network setup guide for a small office
- Palo Alto / FortiGate / Cisco rule hygiene for SMBs (vendor-neutral)
- network segmentation for a medical office
- guest Wi-Fi done right for professional offices
- small business firewall configuration essentials

Security fundamentals:
- phishing simulation programs: are they worth it
- ransomware recovery: the first 24 hours
- password managers for business teams compared
- endpoint detection and response explained for SMBs
- security awareness training that employees do not hate

### Consumer (personal.klaravex.com)

- what to do if you think you have been hacked
- how to set up multi-factor authentication on every account
- Wi-Fi not working: fixes for Windows and Mac
- computer running slow: how to speed it up
- locked out of your email account: how to recover access
- how to spot a phishing email in 10 seconds
- how to back up your family photos safely
- printer not connecting: step-by-step fixes
- how to move everything to a new computer
- is this pop-up a scam: how to tell
- how to set up parental controls that actually work
- browser running slow or crashing: how to fix it
- how to safely dispose of an old computer or phone
- Windows update keeps asking to restart: what to do
- how to stop robocalls and spam texts
- smart home devices: securing your cameras and doorbells
- how to share files with family without email attachments
- external hard drive not showing up: how to fix it

## Inputs

- This charter and `revenue-agents/README.md`.
- **Current problems brief (mandatory read):**
  `revenue-agents/outbox/kb/inputs/current-threats.md` — actively exploited
  vulnerabilities refreshed daily from the CISA KEV catalog. When an entry is
  relevant to Klaravex audiences (SMB business stacks or consumer devices),
  prefer a TOPICAL article about it over the evergreen pool. Never invent
  incidents beyond that file; if nothing fits, draft from the pools below.
- Own outbox history (`revenue-agents/outbox/kb/`, including subdirectories) —
  used for both the surface balance check (14 days) and topic dedup (60 days).
- `CLAUDE.md` (voice policy + positioning).
- Recent SEO drafts in `revenue-agents/outbox/seo-blog/` — avoid drafting a
  topic the SEO agent covered this week.

## Outputs

- On each run, first regenerate/fix any of your own previous drafts bearing a
  REJECTED gate verdict (address the listed failures), then produce today's
  new draft.
- One file per session: `revenue-agents/outbox/kb/YYYY-MM-DD-<slug>.md`
  (e.g. `2026-08-21-unifi-small-office-setup.md`) containing:
  - Front-matter block: `surface:` (business | consumer), `topic:` (verbatim
    from the pool), `title:`.
  - The KB article draft (~1,000 words): step-by-step structure, an FAQ block,
    and a closing CTA to klaravex.com (business) or personal.klaravex.com
    (consumer).
  - A one-line reviewer note stating which surface balance and dedup checks
    were run.
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
