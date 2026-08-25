# Klaravex.com — Site Migration & Expansion Plan
**Prepared:** 2026-06-03 · **Owner:** Anthony · **Executor:** Loki + Anthony review
**Source site:** klaravex.com (mature) · **Target:** klaravex.com (thin, needs depth + new lines)

---

## Executive Summary

klaravex.com is **not failing — it's incomplete**. Loki reproduced the itexperts homepage *skeleton* (pillars, stats, outcomes, business/personal split) competently, but everything below the homepage is missing or stubbed: the 14 service detail pages, Pricing, Case Studies, Knowledge Base, Blog, and a real Personal/consumer section. The site also reads as a near-clone of a Berlin/NIS2/DSGVO practice rather than a US firm, and it under-sells the single thing that actually differentiates Klaravex: **a 24/7 AI-first-line support model.**

This plan does five things:
1. **Ports** the proven itexperts content architecture to klaravex.
2. **Americanizes** it (USD, US compliance frameworks, US spelling, US trust signals; drop NIS2/DSGVO/Berlin from the US site).
3. **Makes the AI explicit** as a positioning advantage — transparently, never hidden.
4. **Expands the B2B catalog** beyond Microsoft: AWS, Google Workspace, AI-workflow automation.
5. **Builds the consumer (B2C) side** as a real product: paid IT help, paid resume/job-search, free + disclaimed scam-recovery support.

**Critical correction to current direction:** Loki should stop generating pages ad hoc. It is producing content that "doesn't look like the site" because it has no locked information architecture, content template, or brand spec to work from. Phase 0 below fixes that — give Loki the IA, the page template, and the Americanization ruleset *before* it writes another page.

---

## 1. Objective & Scope

**Objective:** A single Kadence-based klaravex.com that (a) matches itexperts' depth and polish, (b) is unmistakably a US firm, (c) leads with transparent 24/7 AI + human escalation, (d) carries expanded multi-cloud + AI-workflow B2B services, and (e) launches a credible consumer division.

**In scope:** IA, page inventory, content templates, Americanization ruleset, B2B service expansion, B2C service catalog, AI-transparency messaging, phased build plan, legal guardrails, page copy drafts (separate file `02-Content-Drafts.md`).

**Out of scope (this pass):** EU entity / klaravex.eu (separate track per CLAUDE.md), paid-ads strategy, full SEO keyword build (note hooks only), Atera/Loki event-loop integration (Phase 6, future).

**Assumptions:** Kadence + kadence-child theme stays. WordPress on Cloud86. Loki has WP write access. Zoho Assist (consumer) + Atera (B2B) per tooling decisions. Single operator (Anthony) + Loki — every offering must be deliverable by a lean team.

---

## 2. Gap Analysis — klaravex.com vs klaravex.com

| Area | klaravex.com | klaravex.com (now) | Action |
|---|---|---|---|
| Homepage | Polished, bilingual, stats/testimonials/tech grid | Good skeleton, US copy, AI under-stated | Enhance: AI band, US trust row |
| Service detail pages | 14 full pages, 4 pillars | Menu links exist, pages thin/empty | **Build all 14 + 3 new** |
| Pricing | Dedicated page | Missing | Build (USD) |
| Managed Services / Plans | Detailed tiers | "Managed IT Plans" link, thin | Build 3 tiers (Foundation/Assurance/Directive) |
| Case Studies | Full page + quotes | 3 outcome stats only | Build (anonymized, US-framed) |
| Knowledge Base | Yes | Missing | Build (also feeds Loki + SEO) |
| Blog | Yes | Missing | Build shell + 3 seed posts |
| About | Yes | Link exists | Build (US entity, AI model, founder bio) |
| Free IT Assessment | Dedicated funnel page | CTA only → /contact | Build dedicated page |
| Compliance framing | NIS2 / DSGVO / GDPR | Mixed (HIPAA/SOC2 + leftover EU) | **Americanize fully** |
| Consumer section | None (B2B only) | Single stub link | **Build full B2C division** |
| AI positioning | "AI Automation" service only | "AI-powered monitoring" mention | **Make AI the spine, transparently** |
| Multi-cloud | Azure/Microsoft only | Azure/Microsoft only | **Add AWS + Google Workspace** |

**Verdict:** ~25% of the intended site exists. The skeleton is sound; the body is missing. Don't rebuild — fill in, Americanize, and extend.

---

## 3. Americanization Ruleset (give this to Loki verbatim)

**Apply to every page before publishing.**

| Dimension | Berlin original | Klaravex US rule |
|---|---|---|
| Currency | EUR / € | **USD / $** |
| Compliance frameworks | NIS2, DSGVO, GDPR | **HIPAA, SOC 2, NIST CSF, CCPA/CPRA, PCI-DSS** (NIS2/DSGVO only on klaravex.eu, never .com) |
| Spelling | British (optimise, centre, organisation) | **US (optimize, center, organization)** |
| Geography | "Berlin," "on-site in Berlin within 24h" | **"US-based, remote-first, nationwide"** — drop physical on-site promise unless a US metro is defined |
| Language angle | "English-speaking in Germany" | Drop entirely — irrelevant in US |
| Phone | German / WhatsApp `wa.me/...` | **US business number (Google Voice / OpenPhone per checklist)** |
| Dates | DD.MM.YYYY | **MM/DD/YYYY** |
| Legal pages | Impressum / Datenschutz | **Privacy Policy (CCPA/CDPA + GDPR-as-processor), Terms, DPA** |
| Trust signals | NIS2 "29,000 German companies" | US equivalents: "HIPAA penalties up to $1.9M/yr," SMB breach stats |
| Word "compliance" in marketing | used freely | **Per CLAUDE.md: use "readiness / preparation / advisory," not "compliance"** |

**Retain (works in US unchanged):** the 4-pillar structure, "no vendor commissions," "2-hour response," "senior delivery only," the 32%→78% Secure Score / 28-user / 4-hour cutover outcomes (re-label as US firms), certifications (PCNSE, AZ-500, CCNP, CEH, etc.).

---

## 4. AI Transparency Positioning (the differentiator — do NOT hide it)

Research finding: the consumer-IT and MSP markets are **trust-starved** (tech-support scams everywhere). Transparency about AI is a *trust asset* if framed correctly. Frame it around **availability + human accountability + legitimacy signals**, never as "cheaper because a robot does it."

**Master message:** *"Klaravex runs on Loki, our AI support agent — available 24/7 for first response, diagnosis, and common fixes. When something needs a human, it goes straight to a senior engineer. You always know whether you're talking to AI or a person, and a written summary follows every session."*

**Where it lives:**
- **Homepage:** dedicated band ("How Klaravex works: AI + human") + add "24/7" to the stats row.
- **New page `/how-our-ai-works/`:** full explanation — what Loki does, what it never does, when a human takes over, data handling, the legitimacy signals (you initiate the session, you watch the screen, you get a written summary).
- **Every service page:** one-line "AI-assisted, human-accountable" note.
- **Consumer pages:** lead with it — 24/7 is the wedge vs. Geek Squad's queue.

**Guardrails:** label AI vs. human clearly; never imply Loki is a person; never let AI give legal/financial advice (esp. scam-recovery — see §7); state data handling plainly.

---

## 5. Information Architecture (lock this before Loki writes anything)

```
klaravex.com/
├── /                         Home (AI + human, US, dual B2B/B2C entry)
├── /how-our-ai-works/        AI transparency page  [NEW]
├── /about/                   US entity, founder, AI model
├── /contact/                 + Free IT Assessment funnel
├── /free-it-assessment/      Lead magnet                       [NEW]
│
├── /business/                B2B hub
│   ├── /services/
│   │   ├── Cloud & Productivity
│   │   │   ├── microsoft-azure
│   │   │   ├── microsoft-365
│   │   │   ├── aws-cloud                                       [NEW]
│   │   │   ├── google-workspace                                [NEW]
│   │   │   ├── intune-endpoint-management
│   │   │   └── entra-identity
│   │   ├── Network & Security
│   │   │   ├── firewall-network-security  (UniFi + multi-vendor)
│   │   │   ├── it-security-audit
│   │   │   ├── penetration-testing
│   │   │   └── zero-trust
│   │   ├── Infrastructure & Support
│   │   │   ├── windows-server-infrastructure
│   │   │   ├── backup-disaster-recovery
│   │   │   ├── powershell-automation
│   │   │   ├── remote-it-support
│   │   │   └── network-monitoring
│   │   └── Strategy & Transformation
│   │       ├── it-strategy-vcio
│   │       ├── ai-workflow-automation   (expanded)             [NEW/EXPANDED]
│   │       └── it-procurement
│   ├── /industries/  (healthcare, legal-financial, nist-soc2, iso27001-soc2)
│   ├── /managed-it-plans/  (Foundation / Assurance / Directive — USD)
│   ├── /pricing/                                               [NEW]
│   ├── /case-studies/                                          [BUILD OUT]
│   └── /contact/
│
├── /personal/                B2C hub — "Career & Life Reset"    [BUILD OUT]
│   ├── /personal/it-help/                  Paid consumer IT support
│   ├── /personal/family-senior-tech/       Membership, prevention   [NEW]
│   ├── /personal/resume-job-search/        Paid premium-hybrid      [NEW]
│   ├── /personal/job-hunt-tech-kit/        Paid bundle              [NEW]
│   ├── /personal/solo-business-launch-kit/ Paid → B2B on-ramp       [NEW]
│   ├── /personal/ai-skills-coaching/       Paid                     [NEW]
│   ├── /personal/identity-data-cleanup/    Paid (NOT credit repair) [NEW]
│   ├── /personal/privacy/                  Paid + monitoring        [NEW]
│   ├── /personal/scam-recovery/            FREE + disclaimed        [NEW, sensitive — gated]
│   └── /personal/pricing/                  Consumer pricing
│
├── /knowledge-base/          KB (feeds Loki + SEO)             [BUILD OUT]
├── /blog/                    Blog shell + seed posts           [BUILD OUT]
└── /legal/  (privacy, terms, dpa)                              [NEW]
```

**5th pillar consideration:** AWS + Google Workspace fit under "Cloud & Productivity" (now 6 services). AI-workflow automation grows large enough to arguably become its own pillar later ("AI & Automation") — keep under Strategy for launch, split when it has 3+ sub-services.

---

## 6. Expanded B2B Service Catalog

### New / expanded pages (research-backed)

**AWS Cloud Management** [NEW]
- IaaS/PaaS management, migrations (on-prem/other-cloud → AWS), backup/DR, Well-Architected security reviews, FinOps cost optimization.
- Pricing model: flat monthly retainer or 10–25% of AWS spend (per research). Position vs. Azure-only shops.

**Google Workspace Management** [NEW]
- Tenant setup/migration, security hardening, Vault/eDiscovery, Gemini enablement, admin/identity.
- Target the GWS-native segments: startups, agencies, nonprofits (free GWS for 501c3 — strong nonprofit lead-gen angle, ties to CLAUDE.md minority/grant programs).

**AI Workflow Automation** [EXPANDED from "AI Automation Consulting"]
- Concrete packaged use cases: support chatbots (Loki-as-a-service for clients), document processing + RAG over internal docs, invoice/AP automation, email/scheduling automation.
- Stack: n8n (self-hosted, data-residency) primary; Make/Zapier where client prefers.
- Packaging (per research): chatbot build $5K–$15K; RAG chatbot $15K–$35K; managed AI retainer $500–$2,500/mo.
- **This is the flagship "AI-native MSP" proof point — Klaravex runs Loki on itself.**

**Positioning line (multi-cloud moat):** *"Most small MSPs only do Microsoft. Klaravex manages Microsoft 365, AWS, and Google Workspace — and automates the busywork with AI. You're not boxed into one vendor's stack."*

### Managed IT Plans (USD, per CLAUDE.md tiers)
| Tier | Target | Indicative US price | Includes |
|---|---|---|---|
| Foundation | Baseline managed IT | ~$75–100/user/mo | Monitoring, patching, helpdesk (Loki + human), UniFi mgmt, M365/GWS admin |
| Assurance | + Security/MDR | ~$100–150/user/mo | + endpoint security, backup/DR, security reviews |
| Directive | + Compliance + vCISO | ~$150–250/user/mo | + readiness advisory (HIPAA/SOC2/NIST), vCISO, board reporting |

**GTM note (CLAUDE.md):** lead with **Directive** in all sales conversations; Foundation is a delivery mechanism, not the pitch.

---

## 7. Consumer (B2C) Service Catalog

Per your decision: **mixed model** — IT help paid, resume/job-search paid, scam-recovery free + sensitive.

**Organizing theme: "Career & Life Reset."** The consumer division is deliberately built around the moment someone gets knocked down — a layoff, a scam, a forced fresh start — because that's the founder's own story (see §7e). It's a tighter, more defensible wedge than generic "home IT help," and the Solo-Business Launch Kit quietly graduates consumers into B2B clients. Full page copy for all lines is in `02-Content-Drafts.md` (D1–D10, F).

### 7a. Personal IT Help — PAID
- **Scope:** slow/infected PC, malware removal, Wi-Fi/home network, smart-home setup, printer/email/account lockouts, new-device setup & migration, family/senior tech help.
- **Delivery:** Zoho Assist attended link (consumer-initiated — the legitimacy signal) + Loki 24/7 first-line.
- **Pricing (research-anchored):**
  - Per-incident flat: ~$79–$149 (vs Geek Squad $99–$199)
  - Monthly membership: ~$19–$29/mo (vs HelloTech $19.99, Asurion $24.99–$34.99) — 24/7 Loki + priority human, X sessions/mo
- **Differentiator:** 24/7 AI first-line, written summary every session, you watch the screen, no payment before diagnosis.

### 7b. Resume & Job-Search Help — PAID (premium-hybrid)
- **Scope:** ATS-optimized resume, LinkedIn optimization, cover letters, interview coaching, full job-search package.
- **Wedge (research):** "AI does the volume, human does the strategy." AI for ATS keywords/structure; human for positioning/narrative. Results guarantee (interview in 60 days or free redo).
- **Pricing (research-anchored):** resume $199–$499; LinkedIn +$99–$199; full package $499–$799. Undercut Find My Profession exec while beating Talent Inc. quality reputation.
- **Brand fit:** showcases Klaravex as genuinely AI-native; counter-cyclical revenue in a bad job market.

### 7c. Scam Recovery Support — FREE / goodwill (high-liability — strict guardrails)
- **What Klaravex DOES (in scope):** secure compromised devices, remove remote-access malware, harden/recover accounts (MFA, password resets, session revocation), help organize an evidence package, plainly explain reporting channels (FTC, IC3, bank Reg E/Z, AARP), warn about recovery scams.
- **What Klaravex NEVER does:** legal advice, guarantee fund recovery, act as investigator/trace assets, negotiate with banks or scammers, file reports for the client, **charge an upfront fee to recover money** (that pattern *is* the recovery scam).
- **Required on the page (verbatim disclaimers in Content Drafts):** technical assistance only; not attorneys/PIs/financial advisors; no recovery guarantee; we don't file on your behalf without written direction.
- **Why free:** brand trust, SEO, community goodwill, and it removes the single biggest liability vector (taking money to "recover funds"). Funnels naturally to paid Personal IT Help (device cleanup/hardening) and to legitimate referrals (AARP 877-908-3360, legal aid).
- **Decision flag for Anthony:** confirm with US counsel + E&O carrier before publishing 7c. This page touches UPL and fraud-victim vulnerability; the disclaimers reduce but don't eliminate exposure. **Do not publish 7c until E&O is bound (it isn't yet per CLAUDE.md checklist).**

---

### 7d. Additional consumer lines (Career & Life Reset — research-fit, deliverable now)
| Line | Model | Price | Liability note |
|---|---|---|---|
| Job-Hunt Tech Kit (domain/email/portfolio/LinkedIn/interview AV) | Paid | $199–$399 | Low |
| Solo-Business Launch Kit (get independent & online) | Paid → B2B on-ramp | $299–$599 | Low |
| AI Skills Coaching (use AI for job search/admin) | Paid | $75/session, $199 starter | Low |
| Identity & Data Cleanup (post-breach lockdown) | Paid / membership | from $149 | **NOT credit repair (CROA) — security setup only** |
| Privacy Hardening / "Delete Me" (data-broker opt-out) | Paid + monitoring | from $129; $9/mo | Low |
| Family & Senior Tech + Scam-Proofing (prevention) | Membership | $19/mo | Low — recurring |

**Recommended paid core:** Personal IT Help + Resume/Job-Search + Job-Hunt Tech Kit + Solo-Business Launch Kit. **Free/trust layer:** Scam Recovery (gated) + Family/Senior prevention entry.

**Hard "do NOT offer" (licensure/regulatory):** credit repair, debt/financial advice, immigration/employment legal advice, filing benefits/unemployment claims for clients, any money-recovery guarantee.

### 7e. Founder story (brand spine)
The consumer division's "why" is Anthony's own layoff-while-abroad experience (only a flight home offered). Use it on `/about/` and excerpted on the `/personal/` hub — **forward-looking, never bitter; do not name or characterize the former employer.** Full copy: `02-Content-Drafts.md` §F. Separately, the circumstances of that termination (let go while posted in Germany, flight-home-only) may carry German employment-law leverage — pursue with a German *Fachanwalt für Arbeitsrecht* independently of the site; a fact-timeline scaffold is in `03-Germany-Layoff-Timeline.md`.

## 8. Phased Execution Plan

### Phase 0 — Foundations (do FIRST; unblocks Loki) — Day 1–2
| # | Task | Owner | Validation |
|---|---|---|---|
| 0.1 | Lock IA (§5) as the sitemap of record | Anthony | Sitemap approved |
| 0.2 | Create one Kadence service-page **template** (hero, problem, what's included, AI note, outcomes, FAQ, CTA) | Loki | Template page renders |
| 0.3 | Hand Loki the **Americanization ruleset** (§3) + brand spec as a saved instruction | Anthony | Loki echoes rules |
| 0.4 | Draft & approve AI-transparency messaging (§4) | Anthony | Sign-off |

### Phase 1 — Americanize what exists — Day 2–4
- Audit live klaravex pages for EU residue (€, NIS2, DSGVO, Berlin, British spelling) and fix per §3.
- Add homepage AI band + "24/7" stat + US trust row.
- Build `/how-our-ai-works/`.
- **Validation:** grep site for "€", "NIS2", "DSGVO", "Berlin", "optimise/centre" → zero hits on .com.

### Phase 2 — B2B depth (the 14 + 3) — Day 4–10
- Build all 14 ported service pages from the template (Americanized).
- Build 3 new: AWS, Google Workspace, AI Workflow Automation (§6).
- Build Pricing (USD), Managed IT Plans (3 tiers), flesh Case Studies, About, Free IT Assessment.
- **Validation:** every nav link resolves to a real page; no "coming soon"; mobile renders.

### Phase 3 — Knowledge Base + Blog — Day 8–12 (parallel)
- KB structure (doubles as Loki's answer source + SEO).
- Blog shell + 3 seed posts (e.g., "What HIPAA actually requires of a small practice," "Microsoft 365 vs Google Workspace for a 20-person firm," "How our AI support actually works").
- **Validation:** KB articles indexable; Loki can cite them.

### Phase 4 — Consumer division — Day 10–16
- Build `/personal/` hub, `/personal/it-help/` (paid), `/personal/resume-job-search/` (paid), consumer pricing.
- **Hold `/personal/scam-recovery/`** until E&O bound + counsel review (§7c, §9).
- Wire Zoho Assist consumer flow + Loki 24/7.
- **Validation:** booking/contact flow works; pricing live; disclaimers present.

### Phase 5 — Legal, SEO, launch hardening — Day 14–18
- Privacy (CCPA/CPRA + GDPR-as-processor), Terms, DPA, consumer service terms.
- Schema markup, meta, sitemap.xml, redirects, analytics.
- **Validation:** legal pages linked in footer; SEO check passes; forms deliver.

### Phase 6 — Future (post-launch, per CLAUDE.md)
- Atera → Loki proactive event loop (the AI-native MSP differentiator).
- klaravex.eu / EU entity track.
- klaravex.com → redirect to klaravex.com (decision: set up 301 redirect).

---

## 9. Risks, Legal Guardrails & Rollback

| Risk | Severity | Mitigation |
|---|---|---|
| **Scam-recovery page → UPL / liability / victim harm** | High | Publish only after E&O bound + counsel review; mandatory disclaimers; free-only; no fund-recovery claims; refer out |
| Word "compliance" in marketing | Med | Enforce "readiness/advisory" in Americanization grep check (CLAUDE.md) |
| EU residue on US site confuses buyers / dilutes brand | Med | Phase 1 grep validation gate |
| Offering AWS/GWS/AI you can't yet deliver at depth | Med | Only publish services deliverable now; mark genuinely-future as "available Q3" not fake-live |
| Consumer 24/7 promise vs. solo capacity | Med | Loki genuinely covers first-line 24/7; human SLA = "next business hours" for escalation — state honestly |
| FEIE / US-source income tax (CLAUDE.md) | High | CPA before first US invoice — unchanged |
| Resume "results guarantee" over-promises | Low-Med | Define guarantee precisely (interview, not offer; redo, not refund) |
| Loki publishing off-brand pages | Med | Phase 0 template + ruleset gates all generation |

**Rollback:** WordPress revisions enabled — every page edit is revertable. Build new pages as **drafts**, review, then publish (no live editing). Keep klaravex.com intact as a reference until the 301 redirect to klaravex.com is confirmed live. Take a Cloud86 site backup before Phase 1 and before Phase 5.

---

## 10. Immediate Next Actions (this week)
1. Approve the IA (§5) and Americanization ruleset (§3) — these unblock everything.
2. Have Loki build the service-page **template** (Phase 0.2), not more ad-hoc pages.
3. Run the Phase 1 EU-residue grep + AI band on the homepage.
4. **Bind E&O before any scam-recovery or compliance-readiness content goes live.**
5. Use the page copy in `02-Content-Drafts.md` to seed the priority pages.
