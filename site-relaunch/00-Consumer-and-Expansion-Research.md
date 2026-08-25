# Klaravex — Service Expansion Research Brief
**Date:** 2026-06-03 · **Scope:** Consumer (B2C) lines + expanded B2B (AWS / Google Workspace / AI workflows)
**Method:** Multi-agent web research, current (2025–2026) sources, citations inline.

---

## 1. Romance-Scam / Online-Fraud Victim Recovery — what a non-attorney IT firm can safely offer

**Immediate response (all within an IT/security firm's scope):** stop contact, disconnect compromised devices from the internet to kill any active remote session, run full AV/anti-malware, identify and remove unauthorized remote-access tools (AnyDesk, TeamViewer installed under pretext), reset all credentials from a clean device, enroll MFA, revoke OAuth sessions. Evidence preservation is in scope: screenshots, profile URLs, transaction receipts, chat exports, crypto wallet addresses — organized into a package the **client** then submits.

**Reporting channels (who does what):**

| Channel | Role |
|---|---|
| FTC — reportfraud.ftc.gov | Aggregates complaints, feeds 2,000+ LE agencies |
| FBI IC3 — ic3.gov | Can alert banks to freeze funds; builds LE referral packages |
| Bank / card issuer | Reg E (debit/ACH/Zelle): $50 liability cap if reported ≤2 days. Reg Z (credit): $50 cap, most issuers refund 100%. **Wires: not covered, ~10% recovery.** |
| SEC / CFTC / FINRA | Crypto "pig-butchering" investment fraud |
| AARP Fraud Watch Helpline — 877-908-3360 | Free emotional support + guidance, victim support groups |
| Local police | Report number (banks/insurers often require it) |

As of **March 2026**, updated Nacha rules require banks to monitor for authorized-push-payment fraud including romance-scam impersonation — marginally improves Zelle recovery, not a guarantee.

**The "recovery scam" second-fraud problem (must warn about prominently):** Victim data is sold on "sucker lists" immediately; secondary crews impersonate law firms / cyber teams / "fund recovery services," often run by the *same* syndicate. Red flags to publish: any **upfront fee** to recover funds, guaranteed-recovery promises, escalating "tax/insurance/activation" fees, firm-initiated contact, urgency pressure.

**Liability boundary — CRITICAL:**
- **Permitted:** device cleanup, account hardening, evidence organization, plain-language education on what Reg E/Z cover, walking a client through filing reports, referral to AARP / legal aid / consumer-protection attorney.
- **Prohibited / must refer out:** legal advice or statute interpretation (unauthorized practice of law, all 50 states); guaranteeing fund recovery; acting as a private investigator / tracing assets (PI licensure required in most states); negotiating with banks or scammers on the client's behalf; filing government reports for the client without explicit written authorization.
- **Required disclaimers:** "Technical assistance only — not attorneys, PIs, or financial advisors." / "We do not guarantee fund recovery; no legitimate service can." / "We will not file reports on your behalf without your explicit written direction."

**Sources:** FTC Romance Scams; FBI IC3 FAQ; FINRA Pig-Butchering Alert; CFTC Relationship Investment Scam Alert; SEC PR 2025-144; AARP Fraud Watch Helpline + Recovery Scams; CFPB Reg E §1005.6; NICE Actimize Reg E update; TRM Labs ($35B to fraud in 2025, ~$17B pig-butchering); Davis Wright Tremaine Scam Justice Legal Clinic.

---

## 2. US Resume / Job-Search Help — strong demand, premium-hybrid wedge

**Market conditions (demand drivers, 2025–2026):** time-to-hire ~42 days; ATS filters out **75–88%** of resumes before human review; avg posting draws 250+ applicants, 4–6 interviewed; **27.4%** of LinkedIn postings estimated to be "ghost jobs"; seekers submit 32–200+ applications per offer (0.1–2% online success); 72% report negative mental-health impact. Fortune (Mar 2026): "AI raises the floor and floods the room — a decent resume is table stakes."

**Pricing benchmarks:**
- Entry resume $80–$400 (~$220 avg) · Mid-career $200–$600 (~$500) · Executive $750–$2,500+
- LinkedIn optimization +$99–$399 · Cover letter +$50–$150
- Full packages: $439 (Let's Eat, Grandma) → $995 (Find My Profession exec)
- Self-serve AI tools (Teal, Rezi, Jobscan, Kickresume): $7.50–$65/mo

**Competitive gap:** Volume leaders TopResume & ZipJob (both Talent Inc.) have poor reputations (TopResume 438 BBB complaints/3yr; ZipJob 1.25/5). AI tools commoditize the low end but produce generic, recruiter-detectable output. **Defensible wedge: "AI does the volume, human does the strategy"** — AI for ATS keywords/structure, human for positioning/narrative; direct writer access; results guarantee (interview in 60 days or redo). Buyer = mid-career professional, willing to pay $400–$800.

**Sources:** USA Staffing Services; Select Software Reviews (ATS); MintCareer / LiftMyCV (ghost jobs); Resumas; Clearpoint / Find My Profession / ResuPerk (pricing); Fortune Mar 2026; Teal; AiApply; JobStars.

---

## 3. US Consumer (Residential) IT Support — market, pricing, competitors

**Market:** ~$10.06B in 2025, ~7.6% CAGR → $15.61B by 2031; residential = 54.1% of share (Mordor).

**Common paid issues:** slow/infected PC, malware removal, Wi-Fi/home network, smart-home setup, printer issues, email/account lockouts, new-device setup & migration, password/identity cleanup, elderly/family tech help.

**Pricing models:**
- Per-incident flat fee — Geek Squad $7.99–$349.99; common tasks $99–$199
- Annual membership — Best Buy Total $179.99/yr (24/7 support, all home tech)
- Monthly subscription + protection — Asurion Home+ $24.99–$34.99/mo; HelloTech Home $199/yr
- On-demand gig dispatch — HelloTech, Puls ($79–$499/yr tiers)

**Competitors:** Geek Squad (trusted, expensive, retail-bound); HelloTech (national gig dispatch, merged w/ Geekatoo); Asurion/uBreakiFix (carrier-bundled, commoditized); Puls (smart-home installs); Support.com (remote-only); local break-fix.

**Trust / differentiation:** Tech-support **scams** (Microsoft/Apple pop-ups, cold calls demanding remote access) depress consumer confidence — FBI: no legitimate firm initiates unsolicited contact or demands gift-card/wire payment. The **Zoho Assist attended-link model** (consumer clicks a link, no pre-install, scoped temporary access, watches the screen, gets an auto-summary) aligns exactly with FTC trust guidance: **consumer-initiated contact = the legitimacy signal.** A **24/7 AI-first-line (Loki) + human escalation** model differentiates on availability and persistent relationship vs. incumbent phone queues.

**Sources:** Mordor Intelligence; Best Buy; ThatTechJeff / HomeGuide (Geek Squad pricing); HelloTech; Asurion; FTC + FBI tech-support-scam guidance; Zoho Assist AI.

---

## 4. Multi-Cloud (AWS + Google Workspace) + AI-Workflow SMB Positioning

**Google Workspace vs M365:** Together 91% of SMB market. GWS ~50% of domains (small/micro-skewed); M365 ~58% of enterprise seats. GWS dominates **nonprofits** (free for 501(c)(3), incl. Gemini + NotebookLM), **startups** (1yr free Business Plus via Google for Startups), and **agencies** favoring real-time collaboration. Gemini-embedded AI is a 2026 pull factor.

**AWS managed services for SMB:** $3K–$8K/mo small, $8K–$25K/mo mid; models = flat retainer or 10–25% of AWS spend. SMB buys hosting, backup/DR, FinOps cost optimization, Well-Architected security reviews, migrations. AWS updated MSP partner program **Jan 2026** with SMB-focus incentives; 52% of cloud buyers demand managed services.

**AI-workflow automation:** 89% of small businesses use AI for automation (up from 48% in 2024). Top use cases: support chatbots (47% adoption), invoice/AP automation (cuts payment time 45%), document processing + RAG over internal docs, email/scheduling automation. **n8n** is the MSP infrastructure choice (self-hosted, open-source, $10–15/mo, 70+ AI nodes, data-residency control); Make mid-tier; Zapier priciest/easiest. **MSP packaging:** basic chatbot $5K–$15K one-time; RAG chatbot $15K–$35K; enterprise w/ CRM $25K–$85K+; managed AI retainer $500–$2,500/mo.

**Positioning / margin:** 88% of enterprises are multi-cloud — shapes SMB expectations. **Microsoft-only MSPs face a structural ceiling:** CSP direct now requires $1M+ revenue (was $300K) + $16,500/yr Advanced Support — pushing lean MSPs to tier-2 with compressed margins. For a solo/lean MSP, labor = 60–80% of cost; healthy net margin 25–35%; tool sprawl (avg stack 76 products) is the margin killer. **AI-native delivery** (Syncro projects 30% L1/L2 labor reduction by 2026) lowers cost-to-serve. **The moat is not cloud breadth alone — it's being the SMB MSP that manages AWS + Google Workspace + M365 AND closes the monitoring→triage→client-comms loop with a branded AI agent (Loki).**

**Sources:** Fusion Computing; D3V Tech; Google Workspace Nonprofits; Opsio (AWS MSP pricing); AWS APN Blog Jan 2026; Flamingo (MSP pricing); BizTech; n8n vs Zapier (HatchWorks); CustomGPT (MSP AI services); ChannelPro; Omdia; Cloudmore (CSP shake-up); Seceon.

---

## Strategic implications for Klaravex
1. **AI-transparent positioning is an asset, not a liability** — the consumer-IT and MSP markets are both trust-starved; "AI first-line, human when it counts, 24/7" is a *differentiator* if framed around availability + the legitimacy signals (consumer-initiated sessions, written summaries, no payment-before-diagnosis).
2. **Romance-scam help must be free/goodwill + heavily disclaimed** — it is brand/SEO/trust gold but carries UPL and recovery-scam-adjacency risk. Never charge upfront to "recover funds." Never promise recovery.
3. **Resume/job-search = paid, premium-hybrid** — $400–$800 packages, "AI volume + human strategy," results guarantee. Fits Klaravex's "AI-native" brand perfectly and is counter-cyclical revenue.
4. **Multi-cloud + AI workflows = the B2B moat** — lead with it; it directly attacks the Microsoft-only-MSP ceiling Klaravex would otherwise hit.
