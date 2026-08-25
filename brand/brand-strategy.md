# Klaravex — Brand Strategy
*Last updated: May 2026 | Based on Brand Foundation Document v1.0 + EU expansion + AI-forward pivot*

---

## Vision
One brand. Two markets. AI-assisted IT, security, and compliance expertise
delivered to businesses and individuals who cannot justify — or cannot afford —
traditional IT support.

---

## Entity Structure (end state)

| Entity | Market | Billing | Status |
|--------|--------|---------|--------|
| Klaravex LLC (Wyoming) | United States | USD | Active — formed May 2026 |
| Klaravex GmbH/UG (Germany) | European Union | EUR | Future — when EU pipeline materialises |
| klaravex.com | — | — | Active → migrating to Klaravex brand over time |

---

## Positioning Statement
The AI-powered IT and security partner for businesses and individuals who want
enterprise-grade support at a fraction of the traditional cost — without the
agency overhead, the waiting, or the guesswork.

---

## Tagline
**Clarity. Security. Results.**

---

## The Core Differentiator
**AI does the first-line work. Humans handle the rest.**

AI handles first contact, diagnosis, and routine resolution — instantly, 24/7,
at a cost traditional MSPs cannot match. A senior expert steps in for complex
issues, compliance advisory, and strategic work. Clients get faster responses,
lower prices, and no drop in quality. This is not a hidden internal tool —
it is the product.

---

## Brand Voice
- Direct and precise — no marketing fluff, no vague claims
- Competence over enthusiasm — let technical depth do the selling
- **AI-transparent** — we lead with our AI stack, not hide it; specificity over hype
- Compliance-fluent — speak the language of regulated industries natively
- European precision, American directness — structured methodology, plain language
- Accessible — jargon-free for consumers; sharp and technical for business buyers

---

## Markets & Customer Segments

### Business — United States
| Vertical | Regulatory Driver | Cloud Stack |
|----------|------------------|-------------|
| Healthcare-adjacent SMBs | HIPAA Security Rule | M365 / Azure / AWS |
| Legal & financial services | State privacy laws + PCI-DSS v4.0 | M365 / Google Workspace / AWS |
| General SMBs (10–250 employees) | Cybersecurity spend | M365 / Google Workspace / AWS |

> **Out of scope — Defense/DIB/CMMC:** Klaravex does not pursue defense industrial base clients or CMMC 2.0 engagements. ITAR exposure is not acceptable at this stage. Decision made May 2026 — revisit only after dedicated export controls counsel and structural separation are in place.

### Business — European Union
| Vertical | Regulatory Driver | Cloud Stack |
|----------|------------------|-------------|
| Critical infrastructure & digital operators | NIS2 Directive | Any |
| Financial sector | DORA (live Jan 2025) | Any |
| All EU businesses handling personal data | GDPR | Any |
| General SMBs seeking enterprise credibility | ISO 27001 | M365 / Google Workspace / AWS |
| Healthcare | EU Medical Device Regulation + GDPR | Any |

### Consumer / Residential (US + EU)
Everyday individuals who need reliable, affordable IT help without jargon or
agency overhead. AI handles common issues instantly; a human expert is always
one escalation away.

Examples: device setup, email and account issues, password and identity help,
home network setup, smart home/IoT, data recovery guidance, scam and phishing
response, software and subscription management.

---

## Service Tiers

### Business Tiers (per-user/month)

| Tier | Price Anchor | Positioning |
|------|-------------|-------------|
| Foundation | ~$75–100/user/mo | Operational baseline. AI-assisted, human-supervised. |
| Assurance | ~$100–150/user/mo | Security-aware operations. Post-incident or risk-aware. |
| Directive | ~$150–250/user/mo | Compliance + strategic depth. Regulated industries. |

**GTM rule:** Always lead with Directive. Foundation is a delivery mechanism, not the pitch.

### Consumer Tiers

| Tier | Model | Price Anchor | Positioning |
|------|-------|-------------|-------------|
| Essentials | Monthly subscription | ~$19–29/mo | Ongoing AI-first support; unlimited common issues |
| Per-Incident | Pay-as-you-go | ~$39–79/incident | One-off fixes with no commitment |

**Cloud coverage:** Microsoft 365, Google Workspace, AWS, Apple/iOS, Android, Windows, macOS.

---

## Cloud Platform Coverage
- **Microsoft 365 / Azure** — anchor platform; deepest compliance and security tooling
- **Google Workspace** — full support; growing SMB and consumer base
- **Amazon Web Services** — infrastructure, storage, IAM, business services

---

## Domain Portfolio

| Domain | Purpose | Status |
|--------|---------|--------|
| klaravex.com | Primary — US + global | ✅ Registered |
| klaravex.eu | EU market expansion | ✅ Registered — keep |
| klaravex.io | Defensive hold | ✅ Registered |
| claravex.com | Spelling redirect (K vs C) | Check availability |

---

## Competitive Position
- Cannot win on price against commodity Tier-1 MSPs on labor alone — do not try
- **Win on AI leverage:** faster resolution, lower cost, 24/7 availability, no per-technician scaling constraint
- **Win on transparency:** competitors hide AI use; we make it the product
- Compliance vertical expertise + EU/US dual-market is a structural moat
- Consumer segment is underserved by MSPs entirely — no credible AI-native competitor yet
- Berlin base = EU credibility + timezone coverage for European clients
- Wyoming LLC = US credibility + privacy + simple structure for US clients
- PE roll-ups are commoditising mid-tier MSPs — quality gap creates opportunity

---

## AI Delivery Model
- **First-line: Loki** — the proprietary AI agent handles diagnosis, common fixes, guided self-service — instant response, 24/7. Loki is deployed on the Klaravex Hetzner instance and configured per brand/market via environment variables.
- **Second-line:** Senior human expert (Anthony) for complex issues, compliance advisory, strategic work — escalated by Loki when confidence threshold is not met
- **Transparency rule:** all client-facing communications identify when Loki is handling the interaction
- **Quality gate:** Loki resolutions are sampled and reviewed; human escalation path always available
- **Owned infrastructure:** Loki runs on Klaravex's own stack — no per-seat helpdesk AI cost, no vendor lock-in on the AI layer
- No hiding, no pretending — Loki is the product

---

## klaravex.com Migration Plan
- No hard deadline — migrate when Klaravex brand has sufficient market presence
- Trigger: first EU client signed under Klaravex brand
- Redirect klaravex.com → klaravex.com/eu or klaravex.eu
- Migrate Loki backend branding via env var switch
- Keep German entity active until CPA/Steuerberater advises otherwise

---

## EU Expansion — Next Steps (when ready)
1. Define NIS2 and DORA service offerings specifically
2. Decide GmbH vs UG entity type with German Steuerberater
3. GDPR-compliant DPA template for EU clients
4. EU-specific website section (klaravex.eu or klaravex.com/eu)
5. Translate Directive-tier service into ISO 27001 readiness offering
6. Localise consumer tier for EU (GDPR-compliant data handling, EUR pricing)

---

## Compliance Marketing Rules (both markets)
- Never use 'compliance' as a service descriptor — use 'readiness', 'advisory', 'preparation'
- CMMC/HIPAA/SOC 2/ISO 27001: scope limitations explicit in every SOW
- E&O insurance ($1M+/occurrence) bound before first compliance engagement
- **No defense/DIB/CMMC work** — ITAR route not pursued; no outreach to defense clients
- GDPR DPA signed before any EU client engagement
- AI transparency disclosures in all client-facing materials and terms of service
