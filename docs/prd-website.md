# PRD: klaravex.com WordPress Website
**Status:** DRAFT v0.3  
**Date:** 2026-05-30  
**Owner:** Anthony Stewart  
**Audience:** Developer + Designer building klaravex.com on WordPress (Kadence child theme)  
**Changelog:** v0.3 — Split homepage architecture adopted: `/` is now a path-choice landing; B2B experience lives at `/business/`; consumer experience lives at `/personal/`; remote support explicitly described for consumer segment; nav architecture open question (#13) closed.  
v0.2 — AI-forward positioning (Loki as named first-line agent); Defense/DIB/CMMC vertical removed; multi-cloud coverage; consumer segment added; site architecture updated; AI transparency flagged; SEO targets expanded.

---

## 1. Overview

klaravex.com is the primary lead generation and credibility asset for Klaravex LLC, a managed security, compliance advisory, and AI-powered IT support firm serving US and EU SMBs — and, via a consumer segment, individual/residential clients.

**Scope note (updated May 2026):** Defense/DIB/CMMC is explicitly out of scope. The ITAR route has not been pursued. Do not reference CMMC, DIB, or defense contractors anywhere on the site.

The site runs on WordPress (WP install ID 516) on Cloud86 shared hosting (shared181.cloud86-host.io), using the kadence-child theme (child of Kadence v1.5.0).

DNS is not yet live pending M365 DNS configuration. Site build should be completable and review-ready before DNS cutover.

**Architecture decision (v0.3):** The site uses a split homepage model. `/` is a minimal path-choice landing that routes visitors to either `/business/` (full B2B experience) or `/personal/` (full consumer experience). This keeps the two segments cleanly separated while sharing infrastructure, brand, and sitewide utility pages (`/about/`, `/privacy/`, `/terms/`).

The site is **not** a product or SaaS site. It is a service business site. Its job is to:
1. Route visitors to the right segment (business or personal) immediately
2. Lead with the AI-powered delivery model as the primary differentiator — faster response, lower cost, no compromise on quality
3. Establish immediate credibility with regulated-industry B2B buyers
4. Serve a consumer/residential segment through a clearly separated, accessible experience
5. Convert qualified visitors into discovery calls or subscription sign-ups

### Core Brand Pitch (v0.2 — AI-forward)

> Loki — Klaravex's AI agent — handles first-line support instantly, 24/7. A human expert steps in for anything complex. The result: faster resolution than a traditional MSP, at a lower cost — without sacrificing accountability.

This is the **lead message** on `/business/` and must be reflected in all tier pages, industry pages, the about page, and any page where the service model is described.

A separate React/Bun marketing site prototype exists in `website/` but WordPress on klaravex.com is the production site for v1.

---

## 2. Goals and Success Metrics

### Primary Goals
1. Generate qualified discovery call bookings from US and EU SMB buyers in regulated industries.
2. Convert consumer/residential visitors into Essentials subscriptions or per-incident bookings.

### Secondary Goal
Establish brand credibility sufficient to pass a buyer's informal vetting check (LinkedIn → website → "yes, they're real").

### Success Metrics

| Metric | Target (60 days post-launch) | Measurement |
|--------|------------------------------|-------------|
| Discovery call bookings (B2B) | ≥ 5 per month | Calendly bookings report |
| Lead form submissions (B2B) | ≥ 10 per month | CF7 / GA4 form_submit event |
| Consumer sign-ups (Essentials) | ≥ 3 per month | Payment/subscription platform |
| Consumer per-incident bookings | ≥ 5 per month | Calendly bookings report |
| Split landing click-through rate | ≥ 90% within 10 seconds | GA4 engagement + scroll |
| Avg. time on page (service pages) | ≥ 90 seconds | GA4 engagement_time |
| Bounce rate (B2B homepage) | < 60% | GA4 |
| Organic impressions | Baseline established | Google Search Console |
| Core Web Vitals (mobile) | All green | PageSpeed Insights / CrWV |

### Anti-Goals
- Do not optimize for traffic volume over lead quality
- Do not publish blog content in v1 (deferred — see §10)
- Do not build a client portal in v1
- Do not mix B2B and consumer messaging — keep paths clearly separated

---

## 3. Site Architecture / Page Inventory

### 3.1 Site Map

```
klaravex.com/
├── /                                  Split landing — choose your path
│
├── /business/                         B2B homepage
│   ├── /business/services/            Services overview
│   │   ├── /business/services/foundation/
│   │   ├── /business/services/assurance/
│   │   └── /business/services/directive/    ← primary B2B conversion target
│   ├── /business/industries/          Industries overview
│   │   ├── /business/industries/healthcare/
│   │   ├── /business/industries/legal-financial/
│   │   ├── /business/industries/nis2-dora/
│   │   └── /business/industries/iso27001/
│   ├── /business/how-it-works/        AI + human delivery explainer (conditional — see §4.10)
│   └── /business/contact/             B2B contact + discovery call booking
│
├── /personal/                         Consumer homepage
│   ├── /personal/support/             What's covered + remote support sessions
│   └── /personal/pricing/             Essentials vs Per-Incident pricing
│
├── /about/                            About Klaravex (shared — business and personal)
│
└── [Footer-only / utility]
    ├── /privacy/                      Privacy policy (GDPR + CCPA)
    ├── /terms/                        Terms of service (stub)
    ├── /legal/                        Legal notices and disclaimers
    ├── /thank-you/                    Post-form confirmation (no-index)
    └── /discovery-call/               Calendly embed redirect (no-index optional)
```

### 3.2 Navigation Architecture — Split by Segment (RESOLVED)

**Decision (v0.3 — May 2026):** Split homepage architecture. The site has two distinct navigation contexts:

**B2B nav** (appears on `/business/` and all `/business/*` pages):
- Services (dropdown: Foundation / Assurance / Directive)
- Industries (dropdown: Healthcare / Legal & Financial / NIS2 & DORA / ISO 27001)
- How It Works (conditional)
- About
- Book a Call (primary CTA button)

**Consumer nav** (appears on `/personal/` and all `/personal/*` pages):
- What We Help With → `/personal/support/`
- Pricing → `/personal/pricing/`
- About
- Book a Session (CTA button)

**Shared top-level nav** (appears only on `/` — the split landing):
- Logo only. No navigation menu on the split landing — it is a routing page and should not give visitors a way to bypass the segment choice.

**Cross-segment navigation:**
- Both B2B and consumer navs include a small, non-prominent link in the header or footer: "Looking for [business / personal] IT support? →". This handles edge cases where a visitor arrives at the wrong section.
- `/about/` is accessible from both nav contexts and links back to the appropriate section.

### 3.3 Footer

A shared footer appears on all pages (including both `/business/*` and `/personal/*`):
- Brand: logo, tagline, copyright
- B2B links: Services / Industries / Contact
- Consumer links: Personal IT Support / Pricing / Book a Session
- Company links: About / Privacy / Terms / Legal
- Contact: hello@klaravex.com
- CCPA link: "Do Not Sell or Share My Personal Information"
- Regulatory scope disclaimer band (B2B pages only — consumer pages show a simpler boundary note)

### 3.4 Not-Indexed / Utility

```
/thank-you/               Post-form-submit confirmation (no-index)
/discovery-call/          Calendly embed redirect page (no-index optional)
```

### 3.5 Page Count Summary

**17 content pages + 2 utility pages.** No blog. No case studies in v1.

| Section | Pages |
|---------|-------|
| Split landing | 1 (`/`) |
| B2B homepage | 1 (`/business/`) |
| B2B services | 4 (`/business/services/` + 3 tier pages) |
| B2B industries | 5 (`/business/industries/` + 4 industry pages) |
| B2B how-it-works | 1 (conditional) |
| B2B contact | 1 (`/business/contact/`) |
| Consumer homepage | 1 (`/personal/`) |
| Consumer support | 1 (`/personal/support/`) |
| Consumer pricing | 1 (`/personal/pricing/`) |
| About | 1 (`/about/`) |
| Privacy / Terms / Legal | 3 |

---

## 4. Per-Page Requirements

### 4.1 Split Landing (`/`)

**Purpose:** Route the visitor to the correct segment as quickly as possible. This page should not sell — it should route. The split landing is the first impression; its only job is to make the right next click obvious.

**Design principle:** Minimal. Fast. One decision. Two paths.

**Header:** Logo only. No nav menu. The split landing is not a browseable page — it is a routing page.

**Hero / Main Content**
- Brand tagline (above the two choices): "AI-powered IT support — for your business and your home."
- Two equally weighted choice cards, side by side (or stacked on mobile):

**Card 1 — Business**
  - Label: "For your business"
  - Descriptor: "Managed IT, security monitoring, and readiness advisory for SMBs. AI-powered. Human-backed."
  - CTA button: "Business IT Support →" → `/business/`

**Card 2 — Personal**
  - Label: "For yourself"
  - Descriptor: "Friendly IT help for your devices, home network, and everyday tech problems. Remote, fast, jargon-free."
  - CTA button: "Personal IT Help →" → `/personal/`

**Below the cards (optional):** A single-line trust signal: "Serving US and EU clients since 2026. Wyoming LLC." — keeps it brief, establishes legitimacy without overselling.

**No footer CTA. No social proof band. No service tier list.** All of that lives in the appropriate segment. The split landing must not bleed B2B content toward consumer visitors or vice versa.

**SEO note:** The split landing at `/` is indexed. It is not the primary SEO target — SEO investment goes into `/business/` and the tier pages. The split landing's meta description should reflect the dual-segment nature of the brand.

**Performance note:** The split landing must be the fastest page on the site. Zero images below the fold. Hero image or CSS gradient above the fold only. Target LCP < 1.5s.

---

### 4.2 B2B Homepage (`/business/`)

**Purpose:** Qualify the B2B visitor, communicate the AI-powered delivery model as the primary differentiator, and route them to a service tier, an industry page, or the discovery call.

**Hero Section**
- **Lead message:** The hero MUST open with the AI-forward pitch. Proposed headline direction: "Loki handles it instantly. Your expert steps in when it matters." Alt direction: "AI-powered IT support, backed by human experts. 24/7 — for your business." The precise copy will be finalized in a design pass — but Loki and the AI + human hybrid model must be the first thing a visitor understands.
- Sub-headline: Three lines max. Mention: Loki as the AI agent, human expert escalation, coverage across M365/Azure, Google Workspace, and AWS, US and EU markets, regulated industries. Do not use "compliance" as a noun descriptor.
- Primary CTA: "Book a Discovery Call" → Calendly booking link
- Secondary CTA: "See Our Services" → `/business/services/`
- No hero background video. Static image or CSS gradient only — performance requirement.

**Loki Delivery Model Band**
- Positioned immediately after or integrated with the hero: a concise 3-column or inline explanation of the Loki + human model.
- Proposed structure: "Loki handles it instantly" | "Your expert steps in when needed" | "You get the best of both — speed and judgment"
- Links to `/business/how-it-works/` if that page is built (see §4.10).
- Loki should be named explicitly (not just "AI") — it is Klaravex's named agent and a product identity, not a generic chatbot.

**Social Proof Band**
- Position below the AI delivery model band. In v1, this may be placeholder. Options: cloud platform logos (M365, Google Workspace, AWS — used as "platforms we support", not endorsement), regulatory framework logos (NIST, ISO 27001, NIS2, HIPAA, DORA), or a single punchy pull-quote if available.
- Do NOT fabricate testimonials or imply client relationships that do not exist.

**Service Tiers Summary**
- Three-column card layout. Directive card is visually differentiated (different card treatment, not just highlighted).
- Each card: tier name, one-sentence positioning, price anchor range, CTA to service detail page.
- Cards order (left to right): Foundation | Assurance | Directive — Directive has elevated visual weight.

**Industries Served**
- Two-row grid: US industries (top) | EU industries (bottom), or tabbed toggle.
- Each item links to the relevant industry page.
- Copy must be specific: "Healthcare-adjacent firms managing HIPAA obligations without a dedicated security team" — not "companies in regulated industries."

**Why Klaravex**
- 3–4 items, icon + headline + 2-line description.
- Required themes: Loki AI agent (speed + 24/7 availability), human expert escalation (judgment + accountability), multi-cloud coverage (M365/Azure, Google Workspace, AWS), dual US/EU market expertise, framework-native methodology.

**Homepage CTA Footer**
- Full-width section before page footer. Single CTA: "Ready to know where you stand?" → discovery call booking.

---

### 4.3 Services Overview (`/business/services/`)

**Purpose:** Help B2B buyers understand how the tiers differ and self-select. Not a features matrix — a positioning page.

**Hero Section**
- Headline: "Three tiers. One framework. AI-powered delivery across your entire stack."
- Sub-headline: Mention M365/Azure, Google Workspace, and AWS coverage explicitly — "We meet your team on the platforms you already use."

**Tier Detail Blocks**
Directive (first), Assurance (second), Foundation (third) — reversed from typical MSP ordering to lead with premium.

Each block contains:
- Tier name + price anchor
- Who it is for (1–2 buyer personas, named by role/situation, not company size)
- What is included (5–7 bullets, outcome-oriented, not feature-listed)
- **Platform coverage note:** Each tier block must name the supported platforms (M365/Azure, Google Workspace, AWS) and note that scope is confirmed per engagement
- What it is not (1–2 explicit exclusions — sets honest expectations)
- CTA: "Learn more about [Tier]" → individual tier page

**Loki Delivery Model Note**
Include a brief callout box explaining how Loki — Klaravex's AI agent — handles first-line support across all tiers, with human expert escalation paths defined per SLA. Loki is not an add-on; it is the primary delivery mechanism for first-line support in every tier. Name Loki explicitly in this callout.

**Regulatory Note (mandatory)**
Include a visually distinct callout box on this page:

> "Service scope, regulatory applicability, and compliance claims are defined per engagement in a written Statement of Work. Klaravex does not issue compliance certifications or attestations. Readiness advisory and preparation services are not a substitute for an independent audit or certification body assessment."

This block must appear on every service page.

---

### 4.4 Directive Tier Page (`/business/services/directive/`)

**Priority:** This is the primary B2B conversion page. Build this first.

**Hero**
- Headline: Direct, outcome-named. Proposed: "Strategic security leadership without the CISO salary." Alt: "Compliance readiness, threat coverage, and vCISO advisory — delivered as a managed service, powered by AI."
- Price anchor: "$150–$250/user/month" — present it early, not buried.
- CTA: "Book a Discovery Call" → Calendly

**What's Included**
Structured list, not bullet soup:
- vCISO advisory (quarterly strategy reviews, board-level reporting if applicable)
- Loki AI agent — first-line support and triage (instant, 24/7) with senior engineer escalation path
- Managed detection and response (MDR) — tooling/vendor varies by client environment
- Compliance readiness programs: HIPAA Security Rule gap analysis, SOC 2 Type II readiness, ISO 27001 readiness, NIS2 readiness, DORA readiness (as applicable per client)
- Policy and procedure development
- Incident response planning + tabletop facilitation
- M365 / Azure security hardening + ongoing configuration management
- Google Workspace security hardening + configuration management
- AWS security posture management (IAM, S3 policy review, CloudTrail, GuardDuty configuration)
- Ubiquiti UniFi firewall, VLAN, and network infrastructure management
- Risk register maintenance

**Platform Coverage Note**
Include a brief callout: "We manage security posture across your entire cloud footprint — M365/Azure, Google Workspace, and AWS. Platform coverage confirmed during discovery."

**Scope Disclaimer (mandatory on this page)**
> "Compliance readiness services described on this page are advisory and preparatory in nature. Klaravex does not issue compliance certifications, conduct formal audits, or serve as a third-party assessor. HIPAA compliance determinations require legal counsel. ISO 27001 certification requires engagement with an accredited certification body. All scope and deliverables are defined in a signed Statement of Work."

**Who This Is For**
Named buyer scenarios (4–5), each 2–3 sentences:
- Healthcare-adjacent firm needing HIPAA Security Rule gap remediation with no internal security team
- EU financial firm subject to DORA (live Jan 2025) with no internal CISO
- Legal or financial firm managing client data under state privacy laws + PCI-DSS v4.0
- EU operator needing NIS2 incident reporting and risk management implementation
- Growing SMB with M365, Google Workspace, or AWS infrastructure that needs security advisory and ongoing management without hiring a full-time CISO

**Bottom CTA**
"Talk to us about Directive." → Calendly (not a generic contact form — Directive buyers should book a call, not fill a form).

---

### 4.5 Assurance Tier Page (`/business/services/assurance/`)

**Hero**
- Headline direction: "Security-aware operations. For organizations that have already learned the hard way — or want to avoid it."
- Price anchor: "$100–$150/user/month"
- CTA: discovery call

**What's Included**
- Loki AI agent — first-line support and triage (24/7), with engineer escalation for complex issues
- Proactive monitoring + managed endpoint protection
- M365 / Azure security hardening and monitoring
- Google Workspace security hardening and monitoring
- AWS security monitoring (CloudTrail, GuardDuty, basic IAM review)
- Vulnerability management (scanning + prioritized remediation guidance)
- Security awareness training delivery
- Incident response support (hours-based retainer, not full MDR)
- Quarterly security posture review
- Policy templates (not custom policy writing — that's Directive)

**Platform Coverage Note**
Same callout as Directive tier: "We work across M365/Azure, Google Workspace, and AWS. Platform scope confirmed during discovery."

**Upgrade Path**
Explicit section: "When Assurance becomes Directive." List 3–4 trigger scenarios (e.g., HIPAA audit notice, board-level risk inquiry, EU regulatory notification, ISO 27001 certification program initiated, SOC 2 report required by a customer).

**Scope Disclaimer**
Same mandatory callout box as services overview.

---

### 4.6 Foundation Tier Page (`/business/services/foundation/`)

**Hero**
- Headline direction: "Operational baseline. AI-powered IT management and security hygiene for growing businesses."
- Price anchor: "$75–$100/user/month"
- CTA: contact form (not Calendly — Foundation buyers are lower-urgency, qualify via form first)

**What's Included**
- Loki AI agent — helpdesk support (24/7 first-line triage; engineer escalation with defined SLA)
- M365 / Azure management and user support
- Google Workspace management and user support (where applicable)
- AWS operational support — basic IAM, billing alerts, resource management (where applicable)
- Ubiquiti UniFi network and firewall management (where applicable)
- Endpoint management (Intune / MDM)
- Basic security configuration (MFA enforcement, conditional access baselines)
- Monthly operations report

**Platform Coverage Note**
"Foundation covers the platforms you run. M365/Azure, Google Workspace, and AWS are all supported — scope defined per engagement."

**Explicit Positioning Note (visible on page)**
> "Foundation is our operational baseline — not our security advisory offering. If you have regulatory requirements, an upcoming audit, or a compliance program to build, you likely need Assurance or Directive. Foundation clients can upgrade at any time."

**Upgrade Path**
Same upgrade path section as Assurance — explicit triggers.

---

### 4.7 Industry Pages (`/business/industries/`)

Each industry page follows the same template:

**Template Structure:**
1. Hero: "Regulatory context in plain language" — 2 paragraphs max. What is this regulation? Who does it apply to? What are the consequences of non-readiness?
2. Where SMBs typically fail (3–5 bullets — honest, specific, not alarmist)
3. How Klaravex addresses it — map to specific service tier capabilities; include a note on which cloud platforms are relevant to that vertical
4. Recommended starting tier for this vertical (with rationale)
5. Scope disclaimer (mandatory)
6. CTA: Book discovery call

**NOTE: Defense/DIB — REMOVED**
This page is not built. Defense/DIB/CMMC is out of scope as of May 2026 (ITAR not pursued). Do not create this page, reference CMMC, or mention defense contracting anywhere on the site.

**Industry: Healthcare-Adjacent (`/business/industries/healthcare/`)**
- Regulatory driver: HIPAA Security Rule, HITECH Act. Note: "Adjacent" — Klaravex does not provide clinical or patient-care services.
- Platform context: Many healthcare-adjacent firms run on M365 or Google Workspace; AWS is common for application hosting. Note cross-platform BAA requirements.
- Mandatory disclaimer: "HIPAA compliance determinations require legal analysis by qualified healthcare counsel. Klaravex provides technical and operational readiness advisory only."
- Recommend: Assurance or Directive depending on covered entity vs. business associate status.

**Industry: Legal / Financial (`/business/industries/legal-financial/`)**
- Regulatory drivers: State privacy laws (CCPA, CDPA, SHIELD, BIPA), PCI-DSS v4.0, GLB Act.
- Platform context: M365 is dominant; some firms use AWS for document/data infrastructure. Note multi-platform data governance complexity.
- Note multi-state nexus complexity without providing legal advice.
- Recommend: Assurance (standard) or Directive (firms with breach history, high-value client data, or state bar/regulatory exposure).

**Industry: NIS2 / DORA (`/business/industries/nis2-dora/`)**
- Regulatory driver: NIS2 Directive (transposed by EU member states), DORA (live January 2025).
- Target: EU-based operators and financial entities. Note that NIS2 transposition timeline varies by member state.
- Platform context: EU financial entities commonly span M365 and AWS; Google Workspace is present in some sectors. Cross-platform logging and incident detection are explicit NIS2/DORA requirements — surface this.
- Mandatory disclaimer: "NIS2 scope applicability depends on entity classification under national transposition law in each member state. DORA applies to specific financial entities as defined in Article 2. Klaravex advises clients to obtain legal confirmation of scope before beginning a readiness program."
- Recommend: Directive tier. Berlin presence is a selling point — surface it here.

**Industry: ISO 27001 / GDPR (`/business/industries/iso27001/`)**
- Regulatory driver: ISO/IEC 27001:2022, GDPR (EU and UK GDPR).
- Platform context: ISMS scope definition must address all cloud platforms in use — M365/Azure, Google Workspace, AWS. Klaravex can advise on multi-platform ISMS scope definition.
- Mandatory disclaimer: "ISO 27001 certification is issued by accredited certification bodies, not by Klaravex. Klaravex provides readiness advisory and gap remediation. Certification requires a Stage 1 + Stage 2 audit by an accredited CB."
- GDPR note: "GDPR compliance is an ongoing legal and operational obligation. Klaravex provides technical and organizational measure (TOM) advisory. Legal interpretation of GDPR obligations requires qualified data protection counsel or a licensed DPO."
- Recommend: Assurance (GDPR operational hygiene) or Directive (full ISMS build for ISO 27001).

---

### 4.8 Consumer Homepage (`/personal/`)

**Purpose:** Welcome individual/residential visitors into the consumer segment, establish the Loki + remote human support model, and route them to support details or pricing.

**Tone:** Warm, plain-spoken, and human. No acronyms, no regulatory language. Write for someone who is not technical and may feel slightly embarrassed to ask for help. This page should feel like talking to a knowledgeable friend, not an IT department.

**Hero Section**
- Headline direction: "Tech not cooperating? We'll sort it out." Alt: "Real IT help — no jargon, no judgment."
- Sub-headline: "Loki — our AI — handles common issues instantly. For anything more, a real expert joins you remotely. No home visits, no long waits, no scripts."
- This sub-headline must explicitly communicate the remote delivery model: a real person joins remotely when Loki can't resolve it — they do not come to your home, but they are real and effective.
- Primary CTA: "Get Help Now" → `/personal/support/`
- Secondary CTA: "See Plans and Pricing" → `/personal/pricing/`

**How It Works (consumer version)**
Brief 3-step explainer, friendly tone:
1. "Describe your problem" — Loki, our AI, starts diagnosing immediately. No phone queue.
2. "Loki resolves most issues instantly" — common device, network, account, and email problems handled automatically.
3. "If needed, an expert joins you remotely" — a real technician takes over your screen, fixes the issue, and explains what they did. Done.

This section must not hide the remote delivery model. Remote support is a feature, not a limitation: "No technician visit required — faster, more convenient, and private."

**What We Help With (overview)**
Display as a friendly icon grid (not a formal list):
- Devices: computers, phones, tablets
- Home networking and Wi-Fi
- Account access and password recovery
- Email setup and issues
- Smart home and IoT devices
- Security: suspected scam or account compromise
- Slow, frozen, or misbehaving computers
- Backups and file transfers

Link: "See the full list →" → `/personal/support/`

**Two Paths**
A simple two-card layout:

| | Essentials | Per-Incident |
|---|---|---|
| **Price** | ~$19–29/month | ~$39–79/issue |
| **Best for** | Ongoing peace of mind | One specific problem |
| **CTA** | Subscribe | Book a session |

Link: "See full pricing and what's included →" → `/personal/pricing/`

**Trust Signal**
Brief, simple: "Real expert. Remote. Fast." — with a one-line explanation of the delivery model. Do not use testimonials or implied client counts that cannot be verified.

**Consumer Boundary Note**
Near the bottom: "Running a small business? Our [business plans](/business/) are designed for that." — keeps this brief and non-legalistic, but redirects business visitors who land here.

---

### 4.9 Consumer Support Page (`/personal/support/`)

**Purpose:** Full explanation of what personal IT support covers, the remote delivery model, and how sessions work — for visitors who want detail before committing.

**Hero**
- Headline: "Everything we can help with."
- Sub-headline: "Remote support — so you get expert help wherever you are, without scheduling a home visit."

**Remote Support — How It Works**
This section must appear prominently on this page. Explicitly describe the remote delivery model:

> "When you book a session or Loki escalates your issue to a human expert, your technician joins you remotely. They'll share your screen (with your permission), diagnose and fix the issue directly, and walk you through what they did. No home visit required — and most issues that need a human are resolved in a single 30-minute session."

Key points to surface:
- Remote = screen-sharing session (technician can see and control your screen with permission)
- Works on Windows, macOS, iOS/Android (where supported by remote tools)
- No hardware failures that require physical repair — if the device is dead, that is out of scope
- Private: sessions are not recorded without consent

**What's Covered (full list)**
Display as a visual icon grid or friendly checklist:
- Setting up a new device (laptop, phone, tablet)
- Email and account access issues
- Password resets and account recovery
- Home network and Wi-Fi troubleshooting
- Printer and peripheral setup
- Smart home / IoT device setup and troubleshooting
- Suspected scam, phishing, or account compromise response
- Slow or misbehaving computers
- Backing up your files and photos
- Moving from one device to another
- Basic software installation and configuration
- Browser, search, and app issues

**What's NOT Covered**
Clearly stated, gentle tone:
- Physical hardware repair (screen cracks, liquid damage, broken components)
- Business IT, server management, or network infrastructure — see [our business plans](/business/)
- Issues that require a physical on-site visit (rare, but if it cannot be done remotely, we'll tell you)

Note for developer: "Personal IT Support is designed for personal use at home. If you're running a business — even a small one — our [business plans](/business/) are the right fit."

**Session Quality Guarantee**
Optional section (if substantiated): Brief statement that if a remote session does not resolve the issue, a follow-up session is included or a refund is available. Flag to Anthony before publishing — this needs a confirmed policy behind it.

**CTA**
Two clear paths at the bottom:
1. "Subscribe for $[price]/month" → `/personal/pricing/`
2. "Book a One-Time Session" → Calendly (consumer event type)

---

### 4.10 Consumer Pricing Page (`/personal/pricing/`)

**Purpose:** Full pricing comparison between Essentials and Per-Incident, with clear CTAs for each.

**Hero**
- Headline: "Simple pricing for real IT help."
- Sub-headline: "No contracts. No hidden fees. Cancel anytime."

**Pricing Table**

| | Essentials | Per-Incident |
|---|---|---|
| **Price** | ~$19–29/month | ~$39–79 per issue |
| **What it is** | Monthly subscription — ongoing access to Loki AI support with unlimited engineer escalations | One-time remote session for a specific problem |
| **Best for** | People who want ongoing peace of mind and fast help whenever something goes wrong | A specific issue you need resolved right now |
| **Loki AI support** | ✓ 24/7 | ✓ 24/7 |
| **Remote expert escalation** | ✓ Included | ✓ Included |
| **Session limit** | Unlimited escalations | 1 session (30 min) |
| **CTA** | Subscribe | Book a session |

**Essentials includes:**
- Loki AI support (24/7) for common issues — instant response, no waiting
- Remote human expert sessions when Loki can't resolve it — included, no extra charge
- No per-session fees while subscribed
- Pricing in USD; EU pricing TBD pending EU entity formation (flag to Anthony)

**Per-Incident:**
- Book a 30-minute remote session via Calendly
- Flat fee, no subscription required
- Technician joins remotely, resolves the issue, explains what they did
- If the session runs over 30 minutes for complex issues, additional time is [TBD — confirm policy with Anthony]

**FAQ (short)**
3–4 frequently asked questions. Suggested:
- "What is a remote session?" — Brief answer explaining screen sharing, no home visit, works on all major devices.
- "What if my issue isn't fixed in the session?" — [pending policy from Anthony]
- "Can I upgrade from per-incident to Essentials?" — Yes.
- "Is my payment information secure?" — Yes, processed by [Stripe/platform TBD].

**Note for developer:** The subscription payment platform for Essentials is not confirmed. See §11, item 14. Build the layout and CTAs, but leave the subscribe CTA as a placeholder or waitlist form until the platform is confirmed.

**No regulatory disclaimers on consumer pricing pages.** Simple, clear language only.

---

### 4.11 How It Works Page (`/business/how-it-works/`) — OPEN QUESTION

**Status:** Not yet decided. See §11, item 15.

**Rationale for building it:** Given that the AI + human delivery model is the primary brand differentiator, a dedicated explainer page increases credibility and reduces buyer skepticism. It answers: "What does AI-powered support actually mean? Who's on the other end?"

**Proposed structure (if built):**
1. The model in plain language: Loki handles first-line triage instantly; human expert takes over when complexity requires it.
2. What Loki does: Route issues, answer common questions, gather context before escalating, guide self-service for known issue types.
3. What the human expert does: Diagnoses complex issues, owns remediation, handles compliance-sensitive decisions, advises on architecture.
4. How escalation works: Defined SLA per tier; not a black box.
5. Data and privacy: What Loki sees, what it doesn't, how data is handled.
6. Applies to both B2B and consumer segments — with appropriate examples for each.

**If not built as a standalone page:** The Loki delivery model explanation must be present on `/business/` (Loki delivery model band — §4.2), on the services overview (§4.3), and on each tier page. It cannot be omitted from the site entirely.

---

### 4.12 About Page (`/about/`)

**Purpose:** Pass the credibility vetting check. Buyers Google the company before the call. Shared across B2B and consumer segments.

**Sections:**
1. **What we are:** 2–3 paragraphs. AI-powered managed security and IT support firm. US entity (Wyoming LLC), Berlin-based principal. Serving US and EU markets, plus a consumer/personal IT segment. Lead with the Loki + human delivery model. No puffery.
2. **How we work:** Loki (Klaravex's AI agent) handles first-line triage instantly, human experts own complex issues and compliance advisory work. Not a ticket queue, not offshore helpdesk. Senior-level delivery, AI-accelerated response. Framework-native (NIST, ISO, NIS2, DORA). Structured engagements with defined deliverables.
3. **Platforms we cover:** M365/Azure, Google Workspace, AWS — explicitly named. "We meet clients on the platforms they already use."
4. **Markets served:** US (healthcare-adjacent, legal/financial, M365/Google Workspace/AWS SMBs) and EU (NIS2, DORA, ISO 27001, GDPR). Consumer/personal segment noted briefly.
5. **Principal bio:** Founder/principal. Specific background — do not write this as a boilerplate "passionate about security" paragraph. Technical + regulatory depth, specific frameworks, years of experience. Berlin base acknowledged.
6. **Entity note:** "Klaravex LLC is a Wyoming limited liability company. EU engagements are conducted under separate data processing agreements. A European entity is in formation." (Update when German entity is formed.)
7. **CTA:** "Work with us" → `/business/contact/`.

**Do Not Include:**
- Team member photos with stock images or AI-generated faces
- Client logos without explicit written permission
- Awards or "recognition" that cannot be verified

---

### 4.13 B2B Contact Page (`/business/contact/`)

**Purpose:** Dual-path lead capture — high-intent B2B visitors book a call, lower-intent visitors fill a form.

**Primary Path:** "Book a Discovery Call" — Calendly embed (30-minute call, B2B qualification pre-screened via Calendly intake questions).
**Secondary Path:** Contact form (CF7 or equivalent) for inquiries that are not discovery-call-ready.
**Consumer Redirect:** A brief note: "Looking for personal IT help? Visit our [Personal IT Support](/personal/) page."

**Calendly Intake Questions (to configure in Calendly, not on the WP page):**
- Company name and primary industry
- Approximate employee count
- Cloud platforms currently in use (M365/Azure, Google Workspace, AWS, other)
- Regulatory context (HIPAA, NIS2, DORA, ISO 27001, GDPR, SOC 2, other, unsure)
- Primary concern (security posture, upcoming audit/assessment, compliance program, incident, general inquiry)
- How they found Klaravex

**Contact Form Fields:**
- Name (required)
- Company (required)
- Email (required)
- Country (required — for GDPR routing logic)
- Message (required, 20-char minimum)
- Privacy consent checkbox (required — "I agree to Klaravex processing my contact data to respond to this inquiry. See our [Privacy Policy].")

**Form Submission Routing:**
- CF7 → hello@klaravex.com via M365 SMTP relay (see §9 for integration spec)
- Confirmation email auto-sent to submitter (plain text)
- Thank-you page redirect: `/thank-you/`

---

### 4.14 Privacy Policy Page (`/privacy/`)

**Requirements:**
- GDPR-compliant (lawful basis, data subject rights, DPO contact, retention periods)
- CCPA-compliant (do not sell, opt-out right, categories of data collected)
- Cookie disclosure (what cookies are set, by whom, purpose, duration)
- Analytics disclosure (GA4 — data sent to Google)
- Calendly disclosure (data sent to Calendly, Inc. — US entity)
- Contact form disclosure (data retained for inquiry response, deletion on request)
- Consumer subscription disclosure (if payment platform is live at launch — data sent to payment processor)
- Last-reviewed date visible
- Not a template dump — must accurately reflect actual data flows on this site

**Note:** Privacy policy is a legal document. Flag to Anthony for legal review before launch.

---

## 5. SEO Requirements

### 5.1 Title Tag and Meta Description Standards

| Page | Title Tag (< 60 chars) | Meta Description (< 160 chars) |
|------|------------------------|--------------------------------|
| `/` (split landing) | Klaravex — Business and Personal IT Support | AI-powered IT support for businesses and individuals. Managed security, compliance readiness, and remote personal help. US and EU. |
| `/business/` | Klaravex — AI-Powered IT Support for Businesses | AI-powered managed IT and security for SMBs. M365, Google Workspace, AWS. US and EU coverage. Instant support, human expertise. |
| `/business/services/` | Security Services — Foundation, Assurance, Directive \| Klaravex | Three managed security tiers. AI-first delivery across M365/Azure, Google Workspace, and AWS. Honest pricing. Senior-level escalation. |
| `/business/services/directive/` | Directive — vCISO + MDR + Compliance Readiness \| Klaravex | Strategic security leadership, managed detection, and compliance readiness — $150–250/user/month. AI-powered + human expert delivery. |
| `/business/services/assurance/` | Assurance — Managed Security for Risk-Aware SMBs \| Klaravex | Proactive security monitoring across M365, Google Workspace, and AWS — $100–150/user/month. |
| `/business/services/foundation/` | Foundation — Managed IT and Security Baseline \| Klaravex | AI-powered IT management, endpoint control, and security hygiene for growing businesses — $75–100/user/month. |
| `/personal/` | Personal IT Support — Help for Home and Devices \| Klaravex | Friendly remote IT help for individuals. AI handles common issues instantly. A real expert joins remotely for anything complex. From $19/mo. |
| `/personal/support/` | What We Can Help With — Personal IT \| Klaravex | Remote IT support for personal devices, home networks, email, passwords, scam response, and more. Instant AI + real expert escalation. |
| `/personal/pricing/` | Personal IT Support Pricing \| Klaravex | Essentials from $19/mo or per-incident from $39. Remote sessions. No home visits. AI-powered with real expert backup. |
| `/business/how-it-works/` | How Klaravex Works — AI + Human IT Support | AI handles first-line support instantly. A human expert steps in for complex issues. See how the Klaravex delivery model works. |
| `/business/industries/healthcare/` | HIPAA Security Advisory for Healthcare-Adjacent SMBs \| Klaravex | HIPAA Security Rule gap analysis and readiness advisory. Technical and operational preparation for covered entities and business associates. |
| `/business/industries/nis2-dora/` | NIS2 and DORA Readiness Advisory \| Klaravex | EU NIS2 and DORA compliance readiness for SMBs. Berlin-based advisory team with direct EU regulatory experience. |
| `/about/` | About Klaravex — AI-Powered IT and Security | AI-first managed IT and security advisory. Wyoming LLC. Berlin-based. M365, Google Workspace, AWS. HIPAA, NIS2, DORA, ISO 27001. |
| `/business/contact/` | Contact Klaravex — Book a Discovery Call | Book a 30-minute discovery call or send a message. Serving US and EU SMBs across M365, Google Workspace, and AWS. |

### 5.2 Schema Markup

Implement the following JSON-LD schema types:

- **`LocalBusiness` / `ProfessionalService`** on `/business/`: name, description, url, areaServed (US + EU), serviceType
- **`Service`** on each tier page: name, description, provider, areaServed, offers (price range)
- **`Service`** on `/personal/`: name, description, provider, areaServed (US), audience (individual/residential), offers (Essentials + Per-Incident price ranges)
- **`Service`** on `/personal/support/`: more detailed service description + delivery method (remote)
- **`BreadcrumbList`** on all inner pages — must reflect the `/business/` and `/personal/` path hierarchy correctly
- **`FAQPage`** on industry pages (build FAQ sections on those pages to support this)
- **`ContactPage`** on `/business/contact/`

Use Yoast SEO or Rank Math (pick one — do not install both). Configure at minimum: XML sitemap, canonical tags, OG tags (title + description + image for social sharing).

**SEO architecture note (split homepage):** The canonical for `/` should remain `/`. The primary SEO targets are `/business/` (B2B) and `/personal/` (consumer). Ensure the sitemap includes both `/business/` and `/personal/` subtrees. Do not set a canonical from `/` to `/business/` — both segments need to be discoverable independently.

### 5.3 Keyword Strategy (v1 — foundational only)

Do not over-optimize in v1. Target informational and navigational queries for initial indexing.

**B2B Priority Terms:**
- "NIS2 readiness consulting"
- "vCISO for small business"
- "HIPAA security advisory"
- "ISO 27001 readiness advisory"
- "DORA compliance advisory"
- "Google Workspace security management"
- "AWS security advisory small business"
- "AI IT support managed services"
- "AI-powered MSP"
- "Loki IT support"

**Consumer / Residential Terms:**
- "personal IT support"
- "remote IT support for home"
- "home IT help subscription"
- "IT help for individuals"
- "someone to fix my computer remotely"
- "help with home network setup"
- "AI IT support home"
- "remote computer help"
- "virtual tech support"

Do not target head terms like "cybersecurity company" or "IT support" (unmodified) — unwinnable at launch.

---

## 6. Performance Requirements

### 6.1 Core Web Vitals Targets (Mobile)

| Metric | Target | Measurement Tool |
|--------|--------|-----------------|
| Largest Contentful Paint (LCP) | < 2.5s (split landing: < 1.5s) | PageSpeed Insights / CrWV |
| Interaction to Next Paint (INP) | < 200ms | PageSpeed Insights / CrWV |
| Cumulative Layout Shift (CLS) | < 0.1 | PageSpeed Insights / CrWV |
| Time to First Byte (TTFB) | < 600ms | WebPageTest |
| PageSpeed Score (Mobile) | ≥ 85 | PageSpeed Insights |

Note: Site is on Cloud86 shared hosting. TTFB budget may be tight — implement object caching (WP Super Cache or LiteSpeed Cache if available on Cloud86) and ensure Kadence's built-in CSS/JS optimization is enabled.

### 6.2 Technical Performance Rules

- No hero video (background or otherwise) on any page
- All images: WebP format, explicit width/height attributes, lazy-load below fold
- Hero image: preload tag in `<head>` — this is the LCP element on most pages
- Split landing (`/`): CSS gradient or minimal SVG only. Zero external image requests. This must be the fastest page on the site.
- Google Fonts: host locally (use Local Google Fonts plugin) — eliminates render-blocking third-party DNS lookup
- Calendly embed: load asynchronously, do not embed on every page — only on `/business/contact/`, the Directive tier CTA, and `/personal/pricing/` per-incident CTA
- GA4: load via `gtag.js` with consent mode v2 (required for EU GDPR compliance — do not fire analytics without consent)
- Minimize plugin count. Target: ≤ 12 active plugins total
- No page builders with bloated output (Elementor, WPBakery). Use Kadence Blocks native builder only.

---

## 7. Legal and Compliance Requirements for the Site Itself

### 7.1 GDPR Cookie Consent (EU Visitors)

A cookie consent solution is required before launch. The site will have EU visitors (NIS2, DORA, ISO 27001, GDPR pages specifically target them).

Requirements:
- Consent before analytics cookies fire (GA4 must not load until consent given)
- Granular consent categories: strictly necessary | analytics | marketing (no marketing cookies in v1 — category present but empty)
- Consent log stored (timestamp, IP hash, consent state) — required for GDPR accountability
- "Reject all" option must be as prominent as "Accept all" — no dark patterns
- Consent banner must not obscure primary content (CLS impact — test)
- Re-consent triggered on policy changes
- Recommended plugin: Complianz or CookieYes (both have WP plugins with consent mode v2 GA4 integration)

### 7.2 Privacy Policy

Requirements described in §4.14. Must be live at launch. No cookie banner without a linked privacy policy.

### 7.3 CCPA

For US visitors (California specifically):
- "Do Not Sell or Share My Personal Information" link in footer
- Can be a section in the privacy policy for v1 rather than a separate page

### 7.4 Legal Disclaimers

The following disclaimers must be present and visible on the site:

1. **Regulatory scope disclaimer** (B2B service pages and industry pages — see §4 for text; NOT on the consumer pages)
2. **Not legal advice:** "Content on this site is informational. It does not constitute legal advice. Regulatory compliance obligations vary by jurisdiction, entity type, and specific facts. Consult qualified legal counsel for compliance determinations."
3. **Certifying body distinction:** On any page referencing ISO 27001, SOC 2, or other certification frameworks — Klaravex does not issue certifications or attestations.
4. **Consumer segment boundary:** The footer disclaimer should note that Klaravex's business service tiers and Personal IT Support are distinct offerings; Personal IT Support is not a substitute for a managed service agreement.

Suggested placement: a sitewide footer disclaimer band (small text, but present and legible on all B2B pages) plus the inline callout boxes on service and industry pages as specified in §4. Consumer pages (`/personal/*`) are exempt from the regulatory disclaimers but include the "for personal use" boundary note.

### 7.5 Terms of Service

A stub Terms of Service page at `/terms/` is required at launch. Full terms are a v2 deliverable. The stub must state: "These terms are in draft. A complete Terms of Service will be published prior to formal service agreement execution. All engagements are governed by a separately executed Master Services Agreement (MSA)."

If the consumer Essentials subscription is live at launch, a consumer-facing terms section must be added: subscription terms, cancellation, refunds, and scope of service for personal use. This is separate from the MSA referenced above.

---

## 8. Analytics and Tracking

### 8.1 GA4 Implementation

- GA4 property: create before launch, link to Search Console
- Consent mode v2: required (see §7.1). Default state for EU: `analytics_storage: denied`. Fire only after affirmative consent.
- Do NOT use Universal Analytics (deprecated). GA4 only.
- Recommended implementation: via Google Site Kit plugin or manual `gtag.js` snippet in child theme header. Do not use both.

### 8.2 Conversion Events to Configure

| Event Name | Trigger | Value |
|------------|---------|-------|
| `generate_lead` | B2B contact form submission (CF7 success) on `/business/contact/` | — |
| `book_discovery_call` | B2B Calendly booking confirmation | — |
| `book_personal_session` | Consumer per-incident Calendly booking | — |
| `consumer_subscription_start` | Consumer Essentials subscription sign-up | — |
| `view_directive_page` | Pageview on `/business/services/directive/` | — |
| `view_personal_homepage` | Pageview on `/personal/` | — |
| `view_personal_support_page` | Pageview on `/personal/support/` | — |
| `view_personal_pricing_page` | Pageview on `/personal/pricing/` | — |
| `split_landing_business_click` | Click on "Business IT Support" card on `/` | — |
| `split_landing_personal_click` | Click on "Personal IT Help" card on `/` | — |
| `click_cta_calendly` | Click on any "Book a Discovery Call" or "Book a Session" link | — |
| `scroll_depth_75` | 75% scroll on service pages | — |

### 8.3 Google Search Console

- Verify domain ownership via DNS TXT record (batch with the DNS cutover)
- Submit XML sitemap — must include both `/business/` and `/personal/` subtrees

### 8.4 No Marketing Pixels in v1

No Facebook Pixel, LinkedIn Insight Tag, or retargeting pixels in v1. Deferred until paid campaign budget is allocated. GDPR consent infrastructure must be in place before any pixel is added.

---

## 9. Integration Requirements

### 9.1 Calendly

- Account type: at minimum Calendly Standard (to enable intake questions and custom confirmation pages)
- **B2B event type:** "Klaravex Discovery Call" — 30 minutes, with full B2B intake questions (§4.13)
- **Consumer event type:** "Personal IT Support Session" — 30 minutes, separate from B2B discovery call. Intake questions: name, device type, operating system, brief description of the issue.
- **B2B embed locations:** Inline embed on `/business/contact/`. Popup embed on Directive tier CTA. Inline embed on Foundation tier if Foundation CTA decision changes (see §11, item 10).
- **Consumer embed locations:** Inline or popup embed on `/personal/pricing/` for per-incident booking. Also linked from `/personal/support/`.
- Confirmation redirect: Calendly's own confirmation page is acceptable in v1. Custom `/thank-you/` redirect is a v2 enhancement.
- Calendly branding: suppress Calendly logo if plan allows

### 9.2 Contact Form

- Plugin: Contact Form 7 (CF7) — already commonly available on Kadence installs
- Alternative: WPForms Lite if CF7 causes issues
- Anti-spam: reCAPTCHA v3 or Cloudflare Turnstile (preferred — no visual friction, no Google dependency)
- SMTP delivery: M365 relay via SMTP AUTH or Azure Communication Services. Do not use WP default `wp_mail()` with no relay — delivery on shared hosting is unreliable.

### 9.3 Consumer Subscription Platform

**Status: TBD — see §11, item 14.** The consumer Essentials subscription requires a payment and subscription management platform. Options include Stripe Billing (via a Stripe-connected WP plugin), WooCommerce Subscriptions, or a hosted Stripe payment link. Decision needed before the consumer subscribe CTA can be wired.

### 9.4 M365 Email Routing

- hello@klaravex.com — primary contact routing destination
- support@klaravex.com — future (not wired to site in v1)
- DNS pre-requisite: MX records for klaravex.com must be configured in M365 before form email routing works. Blocked on DNS cutover.
- SMTP relay for outbound WP mail: configure M365 SMTP connector or use WP Mail SMTP with M365 OAuth or app password.

### 9.5 DNS Cutover Dependencies (not a blocker for build, required for go-live)

| Item | Dependency |
|------|------------|
| Site visible at klaravex.com | A record pointed to Cloud86 IP |
| Email delivery (contact form) | MX records live in M365 |
| Search Console verification | DNS TXT record |
| SSL certificate | Auto-provisioned by Cloud86 after A record propagates |

---

## 10. Out of Scope for v1

| Item | Reason for Deferral |
|------|---------------------|
| Blog / content marketing | Requires consistent publishing cadence — not ready at launch |
| Case studies | Client permission and content required — not available at v1 |
| Client portal / login | Product-level decision, not a marketing site feature |
| Live chat widget | Adds latency, requires monitoring — defer until team capacity exists |
| Pricing calculator | Service pricing is consultative, not self-serve |
| EU-specific subdomain or klaravex.eu redirect | Defer until EU pipeline is material or German entity is formed |
| LinkedIn Insight Tag / retargeting pixels | Requires paid campaign budget and GDPR consent infrastructure tested |
| Multi-language (German, French) | EU language support deferred to v2 |
| Job listings / careers | No hiring pipeline in v1 |
| Partner / integrator directory | Not a v1 GTM requirement |
| Marketing automation (HubSpot, ActiveCampaign) | Deferred until lead volume justifies tooling cost |
| Consumer mobile app | Out of scope for site v1 — web only |
| Consumer live chat / AI chat widget embedded | Deferred; the AI support experience is delivered via the managed service, not a site widget |

---

## 11. Open Questions / Decisions Needed

| # | Question | Impact | Owner |
|---|----------|--------|-------|
| 1 | **Principal bio content:** What specific credentials, frameworks, and years of experience should appear on the About page? | About page copy | Anthony |
| 2 | **Social proof:** Are there any client logos, testimonials, or case study excerpts available for v1, with written client permission? | `/business/`, About page | Anthony |
| 3 | **ITAR / CMMC — RESOLVED (May 2026):** Defense/DIB/CMMC is out of scope. ITAR route not pursued. No action needed; noted here for audit trail. | Closed | — |
| 4 | **E&O insurance status:** Is E&O insurance bound before launch? The site advertising compliance readiness services without E&O creates professional liability exposure. | Launch gate | Anthony |
| 5 | **Calendly plan level:** What Calendly plan is active? Intake questions and logo suppression require Standard or above. Consumer event type also requires Standard. | `/business/contact/` and `/personal/pricing/` | Anthony |
| 6 | **M365 SMTP relay method:** App password, OAuth connector, or Azure Communication Services? Required for contact form routing. | §9.4 | Anthony / infra |
| 7 | **Cookie consent platform:** Complianz or CookieYes? Both are acceptable — pick one before build begins. | §7.1 | Anthony / developer |
| 8 | **EU entity status on About page:** The copy currently reads "A European entity is in formation." Is that accurate at launch, or should it be softened further? | `/about/` | Anthony |
| 9 | **Hero headline A/B test:** Is there appetite to set up an A/B test at launch (requires a separate plugin or Optimize-equivalent) or run single variant first? | `/business/` | Anthony |
| 10 | **Foundation CTA to form vs. call:** This PRD routes Foundation-tier inquiries to the contact form rather than Calendly. Is this correct, or should all three tiers lead to a call? | Conversion path logic | Anthony |
| 11 | **Legal review of privacy policy:** Who drafts the privacy policy — Anthony, outside counsel, or template with legal review? This must be resolved before launch. | Launch gate | Anthony + legal |
| 12 | **Cloud86 caching configuration:** Does the Cloud86 plan for WP install 516 include LiteSpeed Cache or opcode caching? Determines which performance plugin to use. | §6 | Anthony / Cloud86 |
| 13 | **Nav architecture — RESOLVED (v0.3 — May 2026):** Split homepage architecture chosen. `/` is a path-choice landing. B2B lives at `/business/`. Consumer lives at `/personal/`. Separate nav contexts per segment. See §3.2. | Closed | — |
| 14 | **Consumer subscription platform:** Stripe Billing, WooCommerce Subscriptions, or a hosted Stripe payment link? Required before the Essentials subscribe CTA can be wired. If not decided before launch, the subscribe CTA should be a waitlist/notify form. | `/personal/pricing/` | Anthony |
| 15 | **How It Works page:** Build `/business/how-it-works/` as a standalone page, or integrate the Loki + human explanation into existing pages only (B2B homepage band, services overview, tier pages)? If standalone, this is a launch-critical page given the AI-forward brand pivot. | Site architecture, SEO | Anthony |
| 16 | **Consumer pricing in EUR:** If EU visitors land on `/personal/`, should EUR pricing be shown, or USD only pending EU entity formation? | `/personal/pricing/` | Anthony |
| 17 | **AWS scope precision:** What is the precise scope of AWS services Klaravex covers at launch? (IAM, S3 policy, CloudTrail, GuardDuty, billing alerts — or broader?) This affects tier page copy accuracy. | All B2B tier pages | Anthony |
| 18 | **Google Workspace scope precision:** Same as above for Google Workspace. Security hardening scope definition needed before tier page copy is finalized. | All B2B tier pages | Anthony |
| 19 | **Remote session scope for consumer:** What screen-sharing tool is used for consumer remote sessions (e.g., Zoho Assist, AnyDesk, Apple Remote Desktop)? What is the refund/follow-up policy if an issue is not resolved in one session? These need to be stated on `/personal/support/` before launch. | `/personal/support/`, Terms | Anthony |

---

## Appendix A: Plugin Inventory (Recommended — v1)

| Plugin | Purpose | Notes |
|--------|---------|-------|
| Kadence Blocks | Page builder blocks (native to theme) | Already installed |
| Yoast SEO (or Rank Math) | SEO: title tags, sitemaps, schema | Pick one only |
| WP Mail SMTP | Reliable form email delivery | Configure with M365 |
| Contact Form 7 | Contact form on `/business/contact/` | With Cloudflare Turnstile anti-spam |
| Local Google Fonts | Host GF locally for performance | Eliminate third-party DNS |
| Complianz (or CookieYes) | GDPR/CCPA cookie consent + consent mode v2 | Required at launch |
| Google Site Kit | GA4 + Search Console | Or manual gtag — not both |
| WP Super Cache (or equivalent) | Page caching | Check Cloud86 LiteSpeed availability first |

**Hard limit: ≤ 12 active plugins.** Audit before launch. If a consumer subscription payment plugin is added (e.g., WooCommerce Subscriptions), re-audit the plugin count.

---

## Appendix B: Regulatory Copy Constraints — Quick Reference

This table consolidates the mandatory copy rules for developer/designer reference during build. These apply to B2B service pages and industry pages only — consumer pages (`/personal/*`) are exempt from regulatory disclaimers.

**CMMC 2.0 — OUT OF SCOPE.** Do not reference CMMC, DIB, or defense contracting anywhere on the site.

| Framework | Mandatory Limitation Language | Where Required |
|-----------|-------------------------------|----------------|
| HIPAA | "HIPAA compliance determinations require qualified healthcare counsel. Klaravex provides technical advisory only." | `/business/services/directive/`, `/business/industries/healthcare/` |
| ISO 27001 | "Certification is issued by accredited certification bodies. Klaravex provides readiness advisory." | `/business/services/directive/`, `/business/industries/iso27001/` |
| NIS2 | "Scope applicability depends on national transposition law. Confirm scope with legal counsel before beginning a readiness program." | `/business/industries/nis2-dora/` |
| DORA | "DORA applies to specific financial entities as defined in Article 2 of Regulation (EU) 2022/2554." | `/business/industries/nis2-dora/` |
| GDPR | "Legal interpretation of GDPR obligations requires qualified data protection counsel or a licensed DPO." | `/business/industries/iso27001/` |
| SOC 2 | "SOC 2 reports are issued by licensed CPAs. Klaravex provides readiness advisory only." | `/business/services/directive/` |
| General | Never use 'compliance' as a service descriptor. Use: readiness, advisory, preparation. | Sitewide (B2B pages) |

---

*DRAFT v0.3 — 2026-05-30. Subject to change based on open questions in §11 and legal review.*
