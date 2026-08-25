# MSP Launch Readiness Gaps — Research Findings

_7 WebSearches conducted. Sources cited below._

## 1. E&O / Professional Liability + Cyber Liability Insurance
Tech E&O and cyber liability are two distinct, mandatory policies. Tech E&O covers professional failure (bad script, botched migration, SLA breach causing client financial harm); cyber covers attack-driven breach. Entry-level: ~$67/mo E&O, ~$148/mo cyber (TechInsurance, Insureon). MSSP-category firms pay above market due to aggregation risk. Standard starting limits $1M/occurrence / $2M aggregate; some carriers/clients now require $5M–$25M as revenue scales. **Hard rule: E&O and cyber must be bound before the first security- or HIPAA-adjacent engagement.** A single uninsured breach claim against a new advisory firm is existential. MSAs without a contractual liability cap expose the firm to claims exceeding policy limits. 2026 underwriters treat as preconditions to issuance: MFA on all systems, EDR on all endpoints, immutable tested backups, email security, patch SLAs, written IR plan.

## 2. Contract Stack: MSA, SOW, SLA, AUP, BAA
Minimum viable stack: (1) **MSA** — liability cap (tie to ACV or policy limit), IP ownership, data handling, termination; (2) **SOW/Engagement Letter** — exact deliverables, fees, exclusions; (3) **SLA** — specific commitments + remedies, aligned to what E&O actually covers; (4) **AUP**; (5) **BAA** — legally required whenever MSP creates/receives/maintains/transmits PHI for a Covered Entity or BA. HHS explicit: even cloud storage of ePHI by a CSP requires a BAA regardless of whether CSP can read the data.

**Operating without a BAA when PHI is in scope = direct OCR enforcement exposure for both parties.** Penalties $100–$50,000/violation, up to $1.5M/yr per category; criminal up to $250K + 10 yrs for willful. North Memorial settlement ($1.55M) shows OCR enforces BAA failures even absent confirmed breach. BAs are directly liable to OCR, State AGs, and FTC.

## 3. "Compliance" vs "Readiness/Advisory" — Liability Line
Advisory firms differ materially from licensed auditors/certifying bodies. "Compliance" in marketing creates implied warranty of audit-passage; "readiness/preparation/advisory" limits that inference. Contractual protections: (a) explicit scope limitation in every SOW; (b) disclaimer — findings are point-in-time advisory opinion, not a guarantee of regulatory compliance or audit outcome; (c) engagement letter distinguishing "readiness assessment" from "compliance certification" (SOC 2 requires licensed CPA firms; ISO 27001 requires accredited auditors); (d) no warranties on third-party platform security. Primary E&O vector: a client who breached after relying on advice — mitigated by scope limit, MSA cap, bound E&O. SEC Reg S-P (2025) imposed third-party risk requirements on financial-sector clients; SOWs for them should acknowledge the client's independent regulatory obligation.

## 4. Data-Processor Obligations: GDPR DPA + US State Privacy
EU clients via Klaravex LLC as processor: GDPR Art. 28 mandates a signed written DPA **before any processing begins** (electronic OK). EU-US Data Privacy Framework upheld by EU General Court Sept 2025 — operative transfer mechanism; SCCs valid alternative. DPA must specify subject matter, duration, nature/purpose, data type, data-subject categories, and bind processor to: process only on documented instructions; confidentiality; Art. 32 security; sub-processor compliance; support data-subject rights + breach notice (Arts. 33/34). Maintain a ROPA, review quarterly.

US clients: 20 states have comprehensive privacy laws in effect 2026. CCPA/CPRA requires a "Service Provider Contract"; TX/VA/CO/CT similar. **Minimum before onboarding:** (1) MSA w/ data provisions; (2) GDPR DPA (EU); (3) CCPA service-provider addendum (CA-exposed); (4) public privacy policy on klaravex.com covering CCPA + GDPR.

## 5. Trust/Credibility Signals — Overcoming No Track Record
Ranked by effort vs impact:
1. **Microsoft Solutions Partner designation** — Partner Capability Score; surfaces in "Find a Partner"; Solutions Partner for Security highest-signal; achievable in months.
2. **Vanta & Drata partner programs** — free; surface to high-intent compliance buyers already on those platforms.
3. **Framework alignment statements** — public NIST CSF / CIS Controls / HITRUST adherence substitutes for formal cert early; costs only documentation.
4. **Clutch / GoodFirms / G2 profiles** — even 2–3 verified reviews break "no track record"; free.
5. **Founder certs** — CISSP, CISM, Security+, AWS/Azure security specialty; MSP Alliance + CompTIA locator directories free.
6. **Case study substitution** — for first 1–2 clients, detailed written case study (problem→action→quantified outcome, with permission) replaces brand history.

Best neutralizer: **narrow niche claim + one reference client + one relevant framework cert** > broad generalist positioning.

## 6. Multi-State Tax Nexus and Licensing
Post-Wayfair, all 45 sales-tax states enforce economic nexus on revenue alone. Near-universal trigger: **$100,000 annual gross sales per state** (AK, UT, IL removed 200-transaction thresholds 2025–26). Once crossed: register, collect, remit.

Critical MSP complexity: **taxability of managed services + SaaS is state-specific.** ~24–25 states tax SaaS in some form. NY/TX tax SaaS; FL/GA don't. TX taxes 80% of SaaS under "data processing." Bundled offerings can trigger taxability of the entire bundle — **separately stated line items mitigate.** Wyoming (home state): no corporate income tax, minimal services sales tax — low home exposure. Highest-priority monitoring: CA ($500K threshold) and TX ($100K) given SMB density. FEIE does NOT shield US-source LLC pass-through income for a US citizen abroad — CPA before first invoice.

## Sources
- TechInsurance / Insureon — MSP Insurance; MSP Channel 2026; ConnectWise 2025; Coyle Group MSSP
- Compliancy Group — MSP HIPAA BAAs; HHS — BA Contracts / CSP ePHI FAQ; HIPAA Journal 2026; Holland & Hart — BAA Penalties; Kaseya MSP Contract Guide
- LegalClarity / Osano — DPA; iGDPR — GDPR for US Cos; IAPP — DPA for CCPA; Bloomberg Law — US vs EU
- Microsoft Solutions Partner for Security / Partner Capability Score; Nayak.ai — Objection Handling; FeelGoodMSP — Case Studies; InnoSec — Certs
- Numeral — Economic Nexus 2026 / SaaS Tax; TaxCloud; Sales Tax Institute; TaxJar — SaaS; Avalara — Economic Nexus Guide
