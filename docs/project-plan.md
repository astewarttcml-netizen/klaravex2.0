# Klaravex LLC — Project Plan: Current State to First Signed US Client

**DRAFT v0.2 — 2026-05-30**
**Owner:** Anthony Stewart
**Status:** Pre-revenue. LLC formed, no EIN, no bank account, no DNS, no insurance.

> **v0.2 changes from v0.1:** Expanded scope to multi-cloud (M365/Azure + Google Workspace + AWS). Added consumer/residential IT segment with its own acquisition sub-track. Added AI-forward positioning tasks (Loki as first-line support agent). Resequenced critical path to allow consumer launch before B2B compliance gates. Removed CMMC/DIB/ITAR track — explicitly out of scope (decided May 2026). Updated risk register and summary timeline.

---

## Current State Snapshot

| Item | Status |
|------|--------|
| KLARAVEX LLC (Wyoming) | Formed — Articles filed |
| Operating Agreement | Drafted — NOT signed (missing formation date, legal name, iPostal1 address) |
| Domains | klaravex.com / .io / .eu registered |
| WordPress | Installed on Cloud86, Kadence/kadence-child active |
| DNS | Configured ✅ 2026-06-02 → 45.82.191.203 |
| EIN | Obtained ✅ — in 1Password |
| Registered Agent | Appointed ✅ |
| Bank Account | Mercury ✅ 2026-06-01 |
| E&O Insurance | Not bound |
| M365 Tenant | Created + klaravex.com verified ✅ 2026-06-02 |
| M365 Mailboxes | Created ✅ 2026-06-02 |
| SPF / DKIM / DMARC | Configured ✅ 2026-06-02 |
| Stripe | Activated + Mercury connected + products created ✅ 2026-06-03 |
| Social Handles | In progress |
| Revenue | $0 |

---

## Service Scope — Multi-Cloud (as of v0.2)

Klaravex covers three cloud platforms, not M365 alone:

| Platform | Managed Services | Compliance/Advisory |
|----------|-----------------|---------------------|
| Microsoft 365 / Azure | User management, endpoint, Defender, Intune, Entra | HIPAA, NIST 800-171, SOC 2 |
| Google Workspace | Admin, identity, endpoint, Vault | SOC 2, HIPAA, NIST CSF |
| Amazon Web Services | IAM, GuardDuty, Security Hub, Config | FedRAMP readiness, SOC 2, HIPAA |
| Ubiquiti UniFi | Firewall config, VLAN segmentation, network monitoring, access point management | Network security baseline for all tiers |

This expands the ICP and prospect pool materially in Phase 5. All three platforms appear on the website, in the MSA scope, and in outreach messaging.

---

## Client Segments (as of v0.2)

### Segment A — B2B Managed Services + Compliance Advisory
- **ICP:** US companies 50–500 employees, regulated industries (healthcare/HIPAA, SaaS/SOC 2, legal, financial) — across M365/Azure, Google Workspace, and AWS environments. **Defense/DIB/CMMC explicitly excluded.**
- **Service tiers:** Foundation · Assurance · Directive
- **Gate requirements:** E&O insurance required before compliance engagements (HIPAA, SOC 2, ISO 27001). General M365/GWorkspace/AWS managed services do NOT require E&O before starting — but bind it early.
- **Acquisition:** LinkedIn, warm intros, cold email, ISACA/(ISC)² communities

### Segment B — Consumer / Residential IT (NEW in v0.2)
- **ICP:** Individuals and households — remote workers, home office, small family tech stack
- **Pricing:** Essentials subscription ~$19–29/mo (remote support, device health, M365/GWorkspace help) · Per-Incident ~$39–79 (one-off remote session)
- **Gate requirements:** NO E&O gate. Requires: payment processing live, ToS + AI transparency disclosures published, consumer landing page live, Loki configured for Klaravex intake.
- **Acquisition:** SEO, Google Ads, referral/word-of-mouth, Reddit/forums (r/techsupport, r/homelab, r/sysadmin)
- **Onboarding:** ToS acceptance + payment — no MSA. Simpler than B2B.
- **Note:** Revenue per account is lower, but consumer launch can happen EARLIER than B2B compliance engagements — do not wait for Phase 4 gates before starting consumer acquisition.

---

## Critical Path — Two Tracks

### Track 1: Consumer Launch (faster)
```
EIN → Bank Account + Payment Processing → Consumer Landing Page Live →
Loki AI Agent Configured → AI Transparency Disclosures in ToS →
Consumer Acquisition Begins
```

Consumer launch does NOT require: E&O insurance, MSA template, or CPA memo (though CPA memo should inform pricing/invoicing before launch).

### Track 2: B2B Compliance Engagements (full gate)
```
EIN → Bank Account → Bookkeeping Setup → Invoice Template Ready
DNS → M365 Mailboxes → Professional Outreach
E&O Bound ($1M/$2M) → First HIPAA/SOC 2 Compliance Engagement Signed
CPA Consultation → First Invoice Sent (tax position locked)
```

Nothing in B2B compliance contract execution should happen until the CPA consultation is complete. General managed services (M365, GWorkspace, AWS administration without compliance scope) can begin before E&O is bound — but E&O is required before any HIPAA, SOC 2, or ISO 27001 advisory engagement.

**ITAR/CMMC/DIB is explicitly out of scope** (decision made May 2026). Do not re-open without export controls counsel. No ITAR opinion letter is needed or planned.

---

## Phase 1 — Legal Foundation

**Goal:** All formation paperwork complete, EIN in hand, legal and tax advisors engaged.

**Target duration:** 2–4 weeks from start

### Tasks

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 1.1 | Select and appoint Wyoming registered agent | Anthony | 1–2 days | None |
| 1.2 | Obtain EIN (IRS Form SS-4 — online if US SSN available, otherwise fax/mail) | Anthony | 1 day (online) / 4–6 weeks (fax) | None |
| 1.3 | Finalize Operating Agreement — insert formation date, confirm legal name matches Articles, insert iPostal1 address | Anthony | 1–2 days | RA appointed (1.1) |
| 1.4 | Sign and date Operating Agreement | Anthony | Same day as 1.3 | 1.3 complete |
| 1.5 | Engage US attorney — review OA, advise on MSA/BAA/SOW scope, confirm correct entity structure for client contracts | Attorney | 3–7 days to engage | 1.2 in progress |
| 1.6 | Engage US CPA (expat-specialized) — FEIE, German tax treaty analysis, Wyoming/nexus exposure, invoicing structure | CPA | 3–7 days to engage | 1.2 in progress |
| 1.7 | CPA consultation deliverable: written memo covering FEIE position, treaty position, when nexus is triggered, invoice currency and VAT treatment | CPA | 2–4 weeks after engagement | 1.6 engaged |

### Decision Points

- **EIN route:** Can Anthony apply online? (Requires US SSN and US-based access — confirm before attempting fax.) Online = same day. Fax = 4–6 weeks. This is the longest possible bottleneck on the critical path; start immediately.
- **Registered agent selection:** Northwest Registered Agents, Registered Agents Inc., or Incfile — all viable at ~$49–$125/yr. Pick one this week. No meaningful functional difference.
- **Attorney scope:** Determine upfront whether attorney engagement covers (a) OA review only, or (b) OA + MSA + BAA + SOW templates. Bundling scope saves time and legal fees.

### Exit Criteria

- EIN issued and in hand
- Registered agent appointed (confirmation on file)
- Operating Agreement executed (signed, dated, stored)
- CPA engaged and consultation scheduled
- Attorney engaged

---

## Phase 2 — Banking and Financial Infrastructure

**Goal:** Business bank account open, bookkeeping system live, invoice template ready, payment processing configured for consumer tier.

**Target duration:** 1–2 weeks (after EIN in hand)

### Tasks

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 2.1 | Open Mercury or Relay business checking account | Anthony | 1–3 business days | EIN (1.2) |
| 2.2 | Set up bookkeeping (Wave free tier or QuickBooks Simple Start) — chart of accounts, expense categories, revenue accounts | Anthony | 2–3 hours | Bank account (2.1) |
| 2.3 | Connect bank feed to bookkeeping system | Anthony | 1 hour | 2.1 + 2.2 |
| 2.4 | Build invoice template (aligned to CPA memo on currency, payment terms, VAT treatment) | Anthony | 2–3 hours | CPA memo (1.7) or interim CPA guidance |
| 2.5 | Set up Wise Business or equivalent for USD/EUR settlement (Berlin-based receipts) | Anthony | 1–2 days | EIN (1.2) |
| 2.6 | Set up Stripe (or equivalent) for consumer subscription + per-incident billing | Anthony | 2–3 hours | Bank account (2.1) |

### Business Credit Track (added v0.2)

Anthony is a US citizen with SSN — standard personal-guarantee business cards are available from day one. Use this sequence:

**Step 1 — Pre-application (do immediately)**

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 2.7 | Pull US personal credit report — verify score is active and unfrozen | Anthony | 15 min | annualcreditreport.com — free |
| 2.8 | Register for DUNS number at dnb.com — free, ~30 days to activate | Anthony | 30 min | EIN + bank (2.1) |
| 2.9 | Register Experian Business profile (businesscredit.experian.com) | Anthony | 15 min | EIN |
| 2.10 | Register Equifax Business profile (equifax.com/business) | Anthony | 15 min | EIN |
| 2.11 | Set up Nav.com free account — monitors all three bureau scores in one place | Anthony | 15 min | EIN |
| 2.12 | Get dedicated US business phone number (Google Voice free or OpenPhone ~$15/mo) — use on all registrations | Anthony | 30 min | None |
| 2.13 | Open Uline Net-30 account — buy small item; pay 10–15 days early | Anthony | 30 min | EIN + bank |
| 2.14 | Open Quill Net-30 account — buy small item; pay early | Anthony | 30 min | EIN + bank |
| 2.15 | Open Grainger Net-30 account | Anthony | 30 min | EIN + bank |
| 2.16 | Open Crown Office Supplies Net-30 account | Anthony | 30 min | EIN + bank |
| 2.17 | Open Staples Business Credit account | Anthony | 30 min | EIN + bank |
| 2.18 | Open Home Depot Commercial Account | Anthony | 30 min | EIN + bank |
| 2.19 | Set up business directory listings (Google Business Profile, BBB, Yelp, Bing, Apple Maps) — identical NAP on all | Anthony | 1–2 hours | Business phone number (2.12) |

**Step 1b — Register with all three business credit bureaus (week 1)**

Don't wait for vendors to report — register proactively so scores generate as soon as tradelines appear.

| Bureau | URL | Score |
|--------|-----|-------|
| D&B | dnb.com (DUNS — task 2.8) | Paydex |
| Experian Business | businesscredit.experian.com | Intelliscore |
| Equifax Business | equifax.com/business | Business Credit Risk score |

**Step 1c — Supporting setup (week 1)**

| Task | Why | Cost |
|------|-----|------|
| Nav.com free account | Monitors D&B + Experian + Equifax business scores in one place — know what's reporting and when | Free |
| Dedicated US business phone number | Required for consistent NAP; lenders verify it | Google Voice (free) or OpenPhone (~$15/mo) |
| NAP consistency rule | Name, Address, Phone must be identical across every registration — one variation creates duplicate bureau records | — |

**Step 2 — Net-30 vendor tradelines (months 1–3)**

Target 5–7 tradelines in the first 90 days. Open accounts, buy something small ($30–50) each month, and pay **10–15 days early** — D&B Paydex rewards early payment with a higher score than on-time.

| Vendor | Category | Reports to |
|--------|----------|-----------|
| Uline (uline.com) | Shipping/office | D&B, Experian |
| Quill (quill.com) | Office supplies | D&B, Experian |
| Amazon Business | Supplies, Net-30 | D&B |
| Grainger (grainger.com) | Industrial/office | D&B, Experian |
| Crown Office Supplies | Office | D&B, Experian |
| Staples Business Credit | Office | D&B, Experian |
| Home Depot Commercial Account | Hardware/supplies | D&B |

> **Pay early — the fastest Paydex lever:** D&B Paydex is purely payment-timing based. Paying 10–15 days early scores 100 (perfect). Paying on time scores 80. Pay every Net-30 invoice early from day one — it costs nothing extra.

| Payment timing | Paydex score |
|----------------|-------------|
| 30 days early | 100 (perfect) |
| On time | 80 |
| 15 days late | 50 |

**Step 2b — Business directory listings (weeks 1–2)**

Lenders verify these during underwriting. Use identical NAP on all of them.

- Google Business Profile
- Better Business Bureau (free listing — paid membership not required)
- Yelp Business
- Bing Places
- Apple Maps Business

**Credit tier progression**

Business credit builds in tiers — each unlocks the next.

| Milestone | What opens |
|-----------|-----------|
| 3 tradelines reporting | D&B Paydex score generated |
| 5 tradelines + 90 days | Experian Intelliscore generated |
| 6 months + score | Tier 2 cards: Shell fleet, BP Business, Sam's Club Business |
| 12 months + revenue | Tier 3 cards: Amex Business, Chase (if personal credit allows) |
| 2 years + revenue | SBA loans, larger credit lines |

**Step 3 — Business credit card**

Two paths depending on personal credit score. Pull annualcreditreport.com first (task 2.7) to know which path applies.

**Path A — Strong personal credit (650+)**

Apply within 30 days of opening the bank account while account history is short but clean.

| Card | Why | Annual Fee |
|------|-----|-----------|
| **Chase Ink Business Preferred** | Best signup bonus; 3× travel/ads/software — apply first | $95 |
| **Amex Business Gold** | 4× on top 2 spend categories — add after 6 months | $375 |
| **Capital One Spark Cash Plus** | 2% on everything, no foreign transaction fee — good for EU purchases | $150 |

**Path B — Weaker personal credit (below 650)**

Net-30 vendors and DUNS are unaffected — neither checks personal credit. Shift card strategy to balance-based approvals instead of personal-guarantee cards.

| Card | Why it works | Requirement |
|------|-------------|------------|
| **Brex** | No personal guarantee — approves on business bank balance | ~$50K+ in Mercury |
| **Ramp** | Same model as Brex, slightly lower threshold | ~$25K+ in Mercury |
| **Mercury IO** | Tied to Mercury balance — easiest if already banking there | Mercury account holder |
| **Secured business card** | Deposit = credit limit; reports to business bureaus; no credit check | $200–500 deposit |

Chase Ink becomes a 12–18 month target once business revenue and bank history are established.

**Parallel: improving personal credit (Path B only)**

Run alongside business credit building; takes 6–12 months to move the needle materially.

| Action | Impact | Time |
|--------|--------|------|
| Pull report + dispute errors | Can be immediate if errors found | 30–60 days |
| Secured personal card (Discover/Capital One) | Steady score growth | 6–12 months |
| Authorized user on long-standing account | Instant boost if available | Days |
| Pay down utilization below 30% on existing cards | Fastest lever if applicable | 1–2 months |

### Minority Business Grants, Loans & Certification Track (updated v0.3)

Klaravex qualifies as both a Black-owned business and an LGBTQ+-owned business. Dual certification (NMSDC MBE + NGLCC LGBTBE) is the highest-leverage play — two separate Fortune 500 supplier diversity databases, one business. Research current as of May 2026.

**Immediate actions (pre-revenue, no blockers)**

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 2.9 | Apply for Kiva US microloan — 0% interest, up to $15K, no revenue minimum, virtual address may qualify | Anthony | 2–3 hours | EIN + bank account |
| 2.10 | Register on Hello Alice (helloalice.com) — grant aggregator with dedicated Black Business Corner; monitor for open cycles ($5K–$25K) | Anthony | 30 min | None |
| 2.11 | Contact MBDA (Minority Business Development Agency) nearest Business Center — free advisory + capital access help, no residency requirement confirmed | Anthony | 1 hour | None |
| 2.12 | Contact NMSDC re: MBE certification eligibility with virtual address — email certification@nmsdc.org to confirm iPostal1 qualifies; MBE opens Fortune 500 supplier diversity procurement | Anthony | 30 min | EIN |
| 2.13 | Apply for NGLCC LGBTBE certification (nglcc.org) — LGBT Business Enterprise cert; ~$400–$1,000 fee by revenue tier; do alongside NMSDC MBE for dual-certification advantage; unlocks LGBTQ+ supplier diversity programs and NGLCC member grants | Anthony | 1–2 hours | EIN + bank account (Mercury — gating item for most applications) |
| 2.14 | Register on StartOut (startout.org) — free membership; connects LGBTQ+ founders to investors, accelerators, and grant alerts | Anthony | 15 min | None |

**Near-term (once minimal traction / revenue exists)**

| Program | What | Amount | Timing |
|---------|------|--------|--------|
| Google for Startups Black Founders Fund | Equity-free cash + Google Cloud credits + mentorship | Up to $150K | Apply when traction demonstrated — Q2 cycle annually |
| NAACP Powershift Entrepreneur Grant | Cash grant for Black entrepreneurs — rising or established | $25K | Monitor naacp.org for open cycles |
| SoGal Black Founder Startup Grant | Black/multiracial women & nonbinary founders | Up to $10K | Monitor sogalblackfounderstartupgrant.com |
| Founders First National Pride Grant | LGBTQIA+ owned; 1+ year in business, 2–100 employees, <$5M revenue | $25K (25 awarded) | April cycle annually; check for fall cycle |
| QBA Grant Program | LGBTQ+ founders; 5 awards expanding in 2026 | $50K (5 awarded) | Monitor for open cycle |
| Accion Opportunity Fund | CDFI loan, flexible terms | $5K–$250K | Requires $100K+ revenue |
| Comcast RISE | Grant + marketing resources | Varies | Requires 2+ years in operation |

**Residency note:** Mercury bank account is the gating item for almost all grant applications — open it before applying to anything. Most programs accept US-entity owners abroad (Wyoming LLC qualifies), but verify eligibility for each cycle individually.

**Requires operating history / revenue threshold**

| Program | Blocker | When accessible |
|---------|---------|----------------|
| SBA 7(a) / 504 loans | Needs operating history + revenue; US residency confirmed ✅ | Phase 4–5; consult CPA on residency documentation under March 2026 SBA policy |
| SBA 8(a) certification | 9-year program; significant setup; US residency confirmed ✅ | Verify with SBA/CPA — high value if eligible (sole-source federal contracts) |
| Accion Opportunity Fund | Requires $100K+ annual revenue | After first year of revenue |
| Comcast RISE | Requires 2+ years in operation + physical presence in target city | Year 2+ |
| California / LA County grants | Physical CA presence required — iPostal1 (CMRA) disqualifies | If physical CA office established |
| Wyoming minority grants | Wyoming has no minority-specific programs | N/A |

> **SBA 8(a) note:** If eligible, this is one of the highest-value programs available — sole-source federal contracts for 9 years, up to $4.5M per contract for services. Worth a dedicated conversation with an SBA-experienced attorney once the business has 6–12 months of history.

> **Dual certification strategy:** NMSDC MBE + NGLCC LGBTBE = two separate supplier diversity searches at Fortune 500 procurement teams. Certification fees are one-time; the pipeline access is ongoing. Do both in the same window — the paperwork overlaps significantly.

### Decision Points

- **Mercury vs Relay:** Mercury has better API/integrations and is the standard for US tech startups. Relay has slightly better cash management tools. Either is fine. Mercury is the default recommendation.
- **Bookkeeping tool:** Wave is free and sufficient for solo operator at $0 revenue. Move to QuickBooks when annual revenue exceeds ~$100K or when a CPA requires it. Start with Wave.
- **Invoice currency:** Do not finalize until CPA memo is received. Interim assumption: USD invoices to US clients, USD or EUR for EU clients. CPA may override.
- **Consumer payment processor:** Stripe is the default. Supports subscriptions, per-incident charges, and has strong fraud controls for consumer-facing products. Configure before consumer acquisition begins.
- **Business credit card:** Pull personal credit report first (task 2.7) to determine path. Score 650+: Chase Ink Business Preferred within 30 days of opening Mercury. Score below 650: Brex or Ramp (balance-based, no personal guarantee) as primary; Chase Ink as 12–18 month target after revenue and bank history are established. Net-30 vendors and DUNS work regardless of personal credit score.

### Exit Criteria

- Business bank account open and funded (initial deposit)
- Bookkeeping system live with chart of accounts configured
- At least one test invoice generated (not sent)
- Wise or equivalent cross-border account open
- Stripe account configured for consumer billing (subscriptions + one-time payments)
- Personal credit report pulled and score confirmed (determines Path A vs Path B)
- DUNS registration submitted
- At least one Net-30 vendor account opened (Uline or Quill)
- Business credit card application submitted — Chase Ink (Path A) or Brex/Ramp (Path B)

---

## Phase 3 — Online Presence

**Goal:** DNS live, M365 mailboxes operational, website publicly accessible with both B2B and consumer pages, Loki configured for Klaravex, core social handles claimed.

**Target duration:** 1–2 weeks (DNS propagation is the gating item)

### Tasks

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 3.1 | Configure DNS for klaravex.com — point to Cloud86 WordPress hosting | Anthony | 1–2 hours (+ 24–48h propagation) | None (can start now) |
| 3.2 | Set up Microsoft 365 Business Basic — create tenant, add verified domain | Anthony | 2–3 hours | DNS propagated (3.1) |
| 3.3 | Create M365 mailboxes: anthony@klaravex.com (minimum); optionally hello@, support@ | Anthony | 30 min | 3.2 |
| 3.4 | Configure SPF, DKIM, DMARC records for klaravex.com | Anthony | 1–2 hours | 3.2 |
| 3.5 | WordPress site — B2B pages: homepage, services (multi-cloud scope: M365/Azure + GWorkspace + AWS), about, contact, legal pages (Terms, Privacy Policy, cookie notice) | Anthony | 3–5 days | DNS live (3.1) |
| 3.6 | WordPress site — consumer landing page: "Home IT Support" or equivalent; pricing, how to get started, FAQ, Stripe payment link or embedded checkout | Anthony | 2–3 days | DNS live (3.1), Stripe configured (2.6) |
| 3.7 | "How it works" page — explain the AI + human support model: Loki handles first contact and triage, human engineer escalates; include what AI can and cannot do | Anthony | 1–2 days | Loki configuration in progress (3.10) |
| 3.8 | AI transparency disclosures — add to Terms of Service: (a) AI-assisted support disclosure, (b) what data the AI processes, (c) right to request human-only support | Anthony | 2–3 hours | 3.7 |
| 3.9 | Website go-live QA — verify on mobile, check all forms, confirm SSL, check contact form routes to M365 mailbox, confirm Stripe checkout loads | Anthony | 2–3 hours | 3.3 + 3.5 + 3.6 |
| 3.10 | Configure Loki for Klaravex — Klaravex-branded persona, consumer + B2B intake flows, escalation routing to Anthony | Anthony | 2–4 hours | DNS live + Loki backend accessible |
| 3.11 | Claim social handles: LinkedIn company page (Klaravex LLC), Twitter/X (@klaravex), GitHub (klaravex) | Anthony | 2–3 hours | None (can start before DNS) |
| 3.12 | Set up LinkedIn personal profile updates — add Klaravex LLC as current position, update headline for target buyer persona | Anthony | 1–2 hours | 3.11 |
| 3.13 | B2B directory listings (free tier) — Clutch, GoodFirms, G2, UpCity, DesignRush, CloudTango | Anthony | 2–3 hours | Website live (3.5) |
| 3.14 | Consumer directory listings — Google Business Profile, Yelp, Thumbtack (free profile + $100–200 test budget), Bark.com | Anthony | 1–2 hours | Consumer page live (3.6) |
| 3.15 | Apply to Vanta Partners and Drata Partners programs — puts Klaravex in front of active compliance buyers at no cost | Anthony | 1 hour | Website live |
| 3.16 | CompTIA member listing — company profile on connect.comptia.org partner locator | Anthony | 1 hour | EIN + website live |
| 3.17 | Set up Zoho Assist (free tier) — consumer remote session tool; test attended access flow on Windows and macOS before first consumer session | Anthony | 1–2 hours | Consumer page live |
| 3.18 | Set up Atera RMM — create account, configure first client workspace, build agent deployment template; install on at least one test machine before onboarding first B2B client | Anthony | 2–4 hours | First B2B client in pipeline |

### Decision Points

- **DNS host:** Use registrar DNS or Cloudflare. Cloudflare is strongly preferred — adds DDoS protection, analytics, and makes future DNS changes faster. Set up Cloudflare nameservers for klaravex.com before pointing to Cloud86.
- **Website readiness bar for "B2B launch":** Site does NOT need to be perfect before B2B outreach begins in Phase 5. Needs: clear value proposition, multi-cloud services described, contact mechanism, and legal pages.
- **Consumer page readiness bar:** Consumer page must be live before consumer acquisition begins. Required: pricing, working Stripe checkout or booking flow, ToS with AI disclosures, "How it works" page.
- **klaravex.io and klaravex.eu:** Redirect both to klaravex.com via DNS for now. Don't stand up separate WordPress installs.
- **AI first-line support platform: DECIDED — Loki.** Loki is the internal AI agent already running on the Hetzner CX22 backend (shared with itexperts-berlin initially). Loki handles first contact, diagnosis, common fixes, and guided self-service — escalates to Anthony for complex issues. Task 3.10 is to configure Loki's Klaravex persona, intake flow, and escalation routing for both consumer and B2B support. The "How it works" page (3.7) and AI transparency disclosures (3.8) should describe Loki generically (no need to name the underlying model publicly).
- **Tooling stack: DECIDED.** Two tools, two segments — they do not overlap:
  - **Consumer remote sessions → Zoho Assist** (~$12/mo after free tier). Consumer grants attended access via a link; no pre-installed agent required. EU data residency options available (important for EU consumer clients). Free tier sufficient to validate the model before paying.
  - **B2B managed clients → Atera RMM** (~$149/mo per technician, unlimited endpoints). Persistent agent on client machines; covers monitoring, alerting, patch management, remote access, and scripting. Per-technician not per-endpoint pricing means costs don't spike as client count grows.
  - **Loki + Atera integration (future):** Atera detects infrastructure events (disk full, patch failed, service down) → triggers Loki to proactively notify and triage with the client before they call. This is the AI-native MSP differentiator — most MSPs have an RMM but a human has to act on alerts. When Atera's API is integrated with Loki, that loop closes automatically. Plan this for Phase 6 or when the second B2B client is onboarded.

### Exit Criteria

- klaravex.com resolves publicly with valid SSL
- anthony@klaravex.com receives and sends email
- SPF/DKIM/DMARC pass (verify with mail-tester.com or MXToolbox)
- B2B website has: homepage, multi-cloud services, about, contact form, Privacy Policy, Terms
- Consumer landing page live with pricing and working payment/booking flow
- "How it works" page live explaining AI + human model
- AI transparency disclosures in ToS
- Loki configured for Klaravex (consumer + B2B intake flows, escalation routing)
- LinkedIn company page live
- Core social handles claimed

---

## Phase 4 — Revenue Readiness

**Goal:** Payment processing live for consumer tier (can happen in Phase 3). All pre-engagement legal, insurance, and compliance prerequisites in place for B2B compliance engagements. Consumer soft-launch can begin BEFORE this phase is complete.

**Target duration:** 3–6 weeks (E&O insurance is the gating item for B2B compliance; without the ITAR track, this phase is shorter than v0.1)

### Consumer soft-launch gate (subset of Phase 4, can happen earlier)
Consumer acquisition can begin as soon as:
1. Consumer landing page live (Phase 3)
2. Stripe payment processing live (Phase 2)
3. Loki configured for Klaravex consumer intake (Phase 3)
4. ToS with AI transparency disclosures published (Phase 3)
5. CPA has provided at minimum interim guidance on consumer pricing/invoicing

E&O insurance is NOT required for consumer support or general managed services (no compliance scope).

### Tasks

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 4.1 | Obtain E&O (Professional Liability) insurance — $1M per occurrence / $2M aggregate minimum. Broker options: Hiscox, Embroker, Markel | Vendor/Anthony | 1–5 business days (Embroker is fastest for solo operators) | EIN (1.2), business address confirmed |
| 4.2 | Obtain Cyber Liability insurance — assess whether bundled with E&O or separate | Vendor/Anthony | Same application as 4.1 | 4.1 in progress |
| 4.3 | Draft MSA (Master Services Agreement) — attorney reviews; must include: scope limitations, IP ownership, limitation of liability, governing law (Wyoming or state of client), indemnification; multi-cloud scope (M365/Azure, GWorkspace, AWS) | Attorney | 1–2 weeks after engagement | Attorney engaged (1.5), CPA memo (1.7) |
| 4.4 | Draft SOW template — time-and-materials and fixed-fee variants; advisory deliverable definitions for HIPAA, SOC 2, ISO 27001 scopes; managed services SOW covering all three cloud platforms | Anthony + Attorney review | 1 week | MSA drafted (4.3) |
| 4.5 | File USPTO Intent to Use application — Class 42 (Computer and Scientific), mark KLARAVEX | Anthony or IP attorney | 2–4 hours to file; PTO examination 8–12 months | None (file early — clock starts on filing date) |
| 4.6 | Set up DocuSign or equivalent for contract execution | Anthony | 1–2 hours | None |

### Decision Points

- **Insurance broker:** Embroker is the fastest path for a solo operator — fully online, binds same-day for standard E&O. Hiscox is also viable. Markel requires a broker intermediary and takes longer. Target: bound within 2 weeks of starting Phase 4.
- **USPTO DIY vs attorney:** Class 42 ITU is straightforward. Filing fee is $250–$350 per class. DIY is acceptable. Attorney is not required unless there are prior art complications. File early — the clock on constructive use starts at the filing date.
- **Governing law in MSA:** Wyoming is the default (state of formation). Some clients will push for their home state. Attorney should advise on acceptable fallback positions.
- **Multi-cloud MSA scope:** Ensure MSA scope explicitly covers M365/Azure, Google Workspace, and AWS so no amendment is needed when serving clients on non-Microsoft platforms.
- **HIPAA Business Associate Agreement (BAA):** Any HIPAA client engagement where Klaravex handles or accesses PHI requires a signed BAA. Attorney should prepare BAA template alongside MSA.

### Exit Criteria (B2B compliance track)

- E&O insurance bound — certificate of insurance on file
- MSA executed template (attorney-reviewed) ready — multi-cloud scope confirmed, BAA template included
- SOW template (both rate structures) ready — HIPAA, SOC 2, ISO 27001 scopes defined
- USPTO ITU application filed — serial number on file
- DocuSign or equivalent configured

---

## Phase 5 — First Client Acquisition

**Goal:** First US clients engaged across both segments. Consumer acquisition running. B2B first engagement signed, MSA/SOW executed, first invoice sent and paid.

**Target duration:** Consumer: can begin Phase 3/4 (parallel). B2B: 4–12 weeks from Phase 4 completion.

### 5A — Consumer Acquisition Sub-Track

**Can start:** As soon as consumer landing page + Stripe + Loki + ToS disclosures are live (Phase 3 exit).

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 5A.1 | Set up Google Search Console and Google Analytics on klaravex.com | Anthony | 1–2 hours | Website live |
| 5A.2 | SEO baseline — consumer-intent keyword research (e.g. "remote computer support", "home IT help monthly") and on-page optimization of consumer landing page | Anthony | 1–2 days | Consumer page live |
| 5A.3 | Google Ads consumer campaign — small budget ($5–10/day), conversion-optimized to Stripe checkout | Anthony | 2–4 hours setup | Consumer page + Stripe live |
| 5A.4 | Reddit/community presence — establish helpful presence in r/techsupport, r/homelab; no spam, genuine contributions with profile linking to Klaravex | Anthony | Ongoing | None |
| 5A.5 | Referral/word-of-mouth — set up lightweight referral offer (e.g. first month free for referred subscriber) | Anthony | 1–2 hours | Stripe configured |
| 5A.6 | Consumer CRM / support queue — verify Loki ticket routing, session logging, and escalation path to Anthony; set up lightweight tracking | Anthony | 2–4 hours | Loki configured (3.10) |
| 5A.7 | First consumer subscription activated — onboarding email, first check-in | Anthony | As it happens | All above |

**Onboarding:** ToS click-through + Stripe payment — no MSA needed. Keep it frictionless.

### 5B — B2B Outreach Sub-Track

**Positioning:** Klaravex is not a body-shop. The ICP is:
- US companies in regulated industries — healthcare (HIPAA), SaaS (SOC 2), legal, and financial — across M365/Azure, Google Workspace, and AWS environments. **No defense/DIB/CMMC clients.**
- Typically 50–500 employees, no in-house compliance function or overwhelmed team
- Buying decision made by CISO, CTO, VP Engineering, or GC — not procurement

**Multi-cloud ICP note:** Expanding from M365-only to M365 + GWorkspace + AWS materially widens the addressable prospect list. SOC 2 SaaS clients span all three platforms; HIPAA clients are mixed M365/AWS; legal and financial are primarily M365.

**Outreach channels (priority order):**
1. LinkedIn — Anthony's personal network + targeted connection + content
2. Warm introductions — former colleagues, World Bank/Merrill/FDH network
3. Cold email (M365 + Apollo or Hunter.io) — ICP company + contact research
4. Industry events / communities — ISACA, (ISC)², HIMSS (healthcare IT), local SMB groups
5. Referrals from consumer clients to their small business needs

| # | Task | Owner | Duration | Dependency |
|---|------|-------|----------|------------|
| 5B.1 | Define ICP precisely — segment priority: (a) HIPAA healthcare (M365 or AWS), (b) SOC 2 SaaS (AWS or GWorkspace), (c) legal/financial managed services (M365) | Anthony | 2–3 hours | Phase 4 complete |
| 5B.2 | Build prospect list — 50–100 named accounts matching ICP across all three cloud platforms, with decision-maker contacts | Anthony (+ AI research) | 3–5 days | 5B.1 |
| 5B.3 | LinkedIn content — 3–5 posts positioning Anthony as a multi-cloud compliance + managed services expert before outreach begins | Anthony | 1–2 weeks | Website live (Phase 3) |
| 5B.4 | Outreach sequence — personalized LinkedIn + email; 5-touch sequence, 14-day cadence; lead with insight not pitch | Anthony | 1 week to build sequence | 5B.2 + M365 live |
| 5B.5 | Discovery call script — outcomes-focused, not feature-dump; MEDDIC or SPIN framework | Anthony | 2–3 hours | 5B.1 |
| 5B.6 | Proposal template — scoped to advisory deliverables, value-based pricing anchors, timeline | Anthony | 3–5 hours | SOW template (4.5) |
| 5B.7 | Outreach launch — execute sequence, track responses, iterate messaging weekly | Anthony | Ongoing | 5B.3 + 5B.4 |
| 5B.8 | Pipeline management — simple CRM (HubSpot free or Notion table) — deal stage, next action, close date | Anthony | 1–2 hours setup | 5B.7 |
| 5B.9 | First engagement negotiation — MSA redline, SOW scope agreement, rate negotiation | Anthony + Attorney (if needed) | 1–3 weeks | First qualified prospect |
| 5B.10 | First invoice sent | Anthony | Same day as SOW signed | CPA memo (1.7) + bank account (Phase 2) |

### Decision Points

- **HIPAA vs SOC 2 first:** HIPAA gap assessments have a defined deliverable, shorter sales cycle, and strong ICP (healthcare-adjacent companies). SOC 2 readiness is the broadest ICP and works across all three cloud platforms. HIPAA is the recommended first engagement type — it's concrete, billable, and repeatable.
- **Pricing model:** Time-and-materials vs fixed-fee. Fixed-fee is preferred for defined-scope deliverables (gap assessment, readiness report). T&M for open-ended advisory retainers. CPA memo should inform payment terms and milestone structure.
- **Subcontracting path:** If direct B2B client acquisition takes longer than expected, subcontracting to an established MSP or HIPAA/SOC 2 consulting firm as a technical resource is a faster path to first revenue. Lower margin, lower risk, and builds references.
- **Multi-cloud messaging:** Decide whether to lead with "we support your platform" neutrality or to specialize (e.g. "M365 security experts who also cover AWS"). Neutral positioning widens ICP; specialist positioning converts faster. Test both in early outreach.

### Exit Criteria

- At least one consumer subscription active (Track A)
- Signed MSA and SOW on file (Track B)
- First B2B invoice sent (date, amount, payment terms)
- First B2B payment received
- Engagement kickoff completed

---

## Phase 6 — EU Expansion (Future — Outline Only)

**Goal:** Klaravex capable of engaging EU clients, with compliant data processing, appropriate entity structure, and EU-specific service offerings.

**This phase is NOT blocking US launch. Do not begin until Phase 5 is complete and first US revenue is recurring.**

### What needs to happen before first EU client engagement

| Item | Notes |
|------|-------|
| GDPR Data Processing Agreement (DPA) template | Required before any EU client engagement involving personal data. Attorney-drafted. |
| EU entity analysis | Assess whether a German UG/GmbH or EU branch is needed based on client type, volume, and German tax treaty obligations. CPA + attorney. |
| klaravex.eu DNS and site localization | Currently registered. Point to klaravex.com or stand up localized site depending on scale. |
| VAT registration assessment | Anthony as US citizen resident in Germany — CPA must advise on German Umsatzsteuer obligations for B2B services to EU clients. |
| NIS2 / DORA advisory credentials | EU market equivalent of HIPAA/SOC 2. Build out service line once US managed services practice is established. |
| EUCS / cyber certification landscape | Monitor ENISA developments. This is a 2027+ opportunity, not 2026. |

---

## Parallel Workstreams

These tasks have no dependencies on each other or on the critical path. Run them concurrently.

| Task | Earliest Start | Notes |
|------|---------------|-------|
| Configure DNS (3.1) | Now | No dependencies. Do this today. |
| Claim social handles (3.11) | Now | No dependencies. 2 hours. |
| Select registered agent (1.1) | Now | No dependencies. 30 minutes. |
| Start EIN application (1.2) | Now | Highest priority. Longest lead time if fax required. |
| File USPTO ITU (4.5) | Now | Time-sensitive. Clock starts at filing date. |
| Begin attorney search (1.5) | Now | Lead time to engage a good US technology attorney is 1–2 weeks. |
| Begin CPA search (1.6) | Now | Expat-specialized CPAs book quickly. Start search immediately. |
| LinkedIn personal profile updates (3.12) | Now | No dependencies. Warms up network before outreach. |
| Loki Klaravex configuration (3.10) | DNS live | Loki is already running — this is config only. 2–4 hours. |
| LinkedIn content (5B.3) | Phase 3 complete | Start publishing as soon as website is live. |
| Consumer SEO setup (5A.1–5A.2) | Consumer page live | Start immediately after consumer page goes live. No compliance gate. |
| Reddit/community presence (5A.4) | Now | No dependency on website. Build presence early. |
| Google Ads consumer campaign (5A.3) | Consumer page + Stripe live | Does not require E&O. |

---

## What Cannot Move in Parallel (Hard Sequencing)

| Blocker | Gates |
|---------|-------|
| EIN | Bank account, insurance application, M365 domain verification |
| Bank account | Bookkeeping setup, invoice sending, Stripe payout account |
| DNS propagation | M365 tenant setup, website QA |
| M365 mailboxes | Professional B2B outreach at scale |
| CPA consultation memo | First B2B invoice sent (consumer pricing can proceed on interim CPA guidance) |
| E&O insurance bound | Any HIPAA/SOC 2/ISO 27001 advisory engagement signed |
| MSA template attorney-reviewed | Any B2B contract negotiation |
| Loki configured + ToS disclosures published | Consumer launch |
| Consumer landing page + Stripe live | Consumer acquisition |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| EIN via fax takes 4–6 weeks | Medium (if online app fails) | High — delays everything | Apply online first; if online fails, fax immediately and pursue other parallel tasks aggressively |
| CPA consultation delays B2B invoice | Low–Medium | High | Engage CPA in Phase 1; even a preliminary call can unblock invoice structure; consumer billing (Stripe) can proceed with interim guidance |
| E&O insurer requires prior claims history | Low | Medium | Embroker and Hiscox routinely bind new-venture E&O. Mitigated by applying early. Consumer track does not require E&O. |
| LinkedIn cold outreach underperforms | Medium | Medium | Supplement with warm intros; referral from consumer clients; ISACA/HIMSS community presence as fallback |
| Website perfectionism delays launch | Medium | Low–Medium | Time-box B2B website work to 3–5 days and consumer page to 2–3 days. Ship it. Iterate. |
| Loki configuration delays consumer launch | Low–Medium | Medium (consumer launch gate) | Loki is already running on Hetzner; this is a configuration task, not a build task. Budget 2–4 hours. Should not block launch. |
| Loki first-line quality is poor at launch | Medium | Medium (consumer trust/refund risk) | Set conservative scope at launch (triage + FAQ only, not autonomous resolution). Expand capabilities after first 10–20 sessions. Clear human-escalation path always available. |
| Multi-cloud positioning dilutes message | Low–Medium | Low–Medium | Lead with platform-agnostic compliance posture in B2B outreach; tailor platform-specific messaging in discovery. Don't try to be three things in one headline. |
| Consumer pricing too low to cover Loki/infra cost | Low | Low | At $19–29/mo, infra cost per subscriber must stay under ~$3–5/mo. Monitor cost per subscriber from day one. Adjust pricing or tier structure if needed. |
| Personal credit report dormant/frozen (expat) | Low–Medium | Low | Pull annualcreditreport.com before any card application. Unfreeze if necessary (24–48h). If score is below 650, shift to Path B (Brex/Ramp) — no blocker on business credit building. |
| HIPAA BAA not in place before healthcare client access to PHI | Low | High | Attorney must prepare BAA template alongside MSA. Never access client PHI without signed BAA on file. |

---

## Summary Timeline (Optimistic / Realistic)

| Milestone | Optimistic | Realistic |
|-----------|-----------|-----------|
| Phase 1 — Legal Foundation | 2 weeks | 4 weeks |
| Phase 2 — Banking + Stripe | +1 week | +2 weeks |
| Phase 3 — Online Presence + Loki configuration | +1 week (parallel with Phase 2) | +2 weeks |
| **Consumer soft-launch (Track A)** | **~4 weeks from today** | **~8 weeks from today** |
| Phase 4 — B2B Revenue Readiness (E&O bound) | +2 weeks | +4 weeks |
| Phase 5B — First B2B client | +4 weeks | +12 weeks |
| **First B2B signed client** | **~10 weeks from today** | **~22 weeks from today** |

**Key differences from v0.1:**
- Consumer revenue can start 6–14 weeks before the first B2B compliance engagement.
- Phase 4 is shorter without the ITAR track — E&O is the only hard gate for B2B compliance work, and it binds in days not weeks.
- The dominant variable for B2B is now sales cycle length (HIPAA/SOC 2 buyers), not regulatory paperwork.
- Overall best-case and realistic timelines both compress vs v0.1.

---

## Open Decision Log

| # | Decision | Status | Options / Resolution | Needed By |
|---|----------|--------|---------------------|-----------|
| D1 | AI first-line support platform | **DECIDED — Loki** | Loki (existing agent on Hetzner CX22). Configured for Klaravex in Phase 3. | Before consumer launch |
| D2 | EIN application route | Open | Online (same day) vs fax (4–6 weeks) | Immediately |
| D3 | Business bank | Open | Mercury vs Relay | After EIN |
| D4 | Bookkeeping tool | Open | Wave vs QuickBooks | After bank account |
| D5 | Multi-cloud B2B messaging | Open | Platform-neutral vs specialist positioning | Before B2B outreach launch |
| D6 | ITAR/CMMC/DIB scope | **DECIDED — out of scope** | No defense clients. No ITAR opinion letter. Decided May 2026. | N/A |
| D7 | HIPAA BAA — attorney drafts vs template service | Open | Attorney-drafted (preferred) vs Legal Zoom/template (faster, riskier) | Before first HIPAA client |
| D8 | Consumer remote session tool | **DECIDED — Zoho Assist** | Free tier to start; attended access only (consumer grants access per session, no persistent agent); EU data residency available; ~$12/mo when paid tier needed | Before first consumer session |
| D9 | B2B RMM tool | **DECIDED — Atera** | ~$149/mo per technician, unlimited endpoints; covers monitoring, patch management, remote access, scripting; per-technician pricing scales cleanly for solo operator | Before first B2B managed services client |
| D10 | Atera + Loki integration | **Future — Phase 6** | Atera detects infrastructure events → Loki proactively triages with client before they call. Plan when second B2B client onboarded or Phase 6 begins. | Phase 6 |

---

*DRAFT v0.2 — 2026-05-30 — Klaravex LLC internal use only*
