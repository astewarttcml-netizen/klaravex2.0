# Klaravex B2B — SMB Market Analysis & Service-Fit Review
**Prepared:** 2026-06-03 · Sources cited inline · Companion to `01-Migration-and-Expansion-Plan.md`
**Purpose:** Research what US SMBs actually need from an MSP in 2026, then grade Klaravex's full service list against that demand — what to lead with, what's table-stakes, what's commodity, and the gaps you're missing.

---

## 1. Market reality (2026)

- SMBs spent ~**$1.1T on IT globally in 2025**, projected **+7.2% in 2026**, shifting from capex to subscription. (Medha Cloud)
- **Cybersecurity is the fastest-growing MSP segment — ~18%/yr vs ~14% for MSP overall.** (Integris) SMB security spend ~**$175B globally in 2026, +16.3% YoY**; SMBs are ~60% of global cyber spend, most of it flowing through service providers. (StationX; Hacker News/Cynomi)
- **71% of SMBs now use MDR / managed SOC** rather than build in-house; **EDR adoption jumped 49%→65%** in a year. (StationX) An SMB of 50–250 spends ~**$43K/yr** on security tools/services alone.
- **Cyber insurance is now the forcing function.** Carriers require **MFA, EDR with 24/7 monitoring, and immutable/tested backups** as table stakes. **73% of small businesses fail their cyber-insurance assessment in 2026**; premiums double or coverage is denied without controls. (Velocity; BASG) This is the single biggest involuntary driver of SMB security spend.
- **Compliance is broad and intensifying.** 85% say compliance is more complex than 3 years ago; **96% of MSPs report high/moderate vCISO demand**; multi-framework clients (NIST CSF 2.0, SOC 2, HIPAA, ISO 27001, PCI, CCPA) are the highest-value segment. (Cynomi; DLCyber)
- **AI/AIOps is the differentiation axis** — 87% of MSPs increasing AI investment; service-desk automation expected to cut ticket volume 40–60%. (Integris/DeskDay) ← *This is literally Klaravex's Loki thesis.*
- **Co-managed IT is the dominant model** in 2026, especially at 100–200 employees (in-house lead + MSP depth). (ITBudgetCalculator)

**Pricing benchmarks (per user/month):** national avg **$125–$300**; basic (helpdesk/patch/monitor) **$100–$150**; premium (SOC monitoring + compliance + vCISO) **$225–$350**. Scales by size: 10–25 users **$200–$400**, 25–100 **$150–$300**. (ITBudgetCalculator; Corsica)
→ **Your tiers (Foundation $75–100 / Assurance $100–150 / Directive $150–250) sit at or BELOW market.** Foundation is arguably underpriced; Directive has clear room to $250–350 given it includes compliance + vCISO. Loki's automation is what lets you defend the lower end profitably — but don't reflexively race to the bottom (per your own GTM note).

---

## 2. What SMBs actually need — ranked by demand

| Rank | Need | Why it's hot | Buying trigger |
|---|---|---|---|
| 1 | **Managed security: MDR / managed SOC + EDR, 24/7** | Fastest-growing spend; 71% adoption | Breach fear + insurance mandate |
| 2 | **Cyber-insurance readiness** (MFA, EDR, immutable backup, IR plan) | 73% fail assessments | Renewal/denial deadline — urgent, high-intent |
| 3 | **Backup & DR — immutable, tested, recoverable** | Insurance + ransomware | Audit/claim review |
| 4 | **Identity & access (MFA, Conditional Access, M365/GWS hardening)** | Blocks 99.9% of automated attacks | Insurance + breach |
| 5 | **Security awareness training + phishing simulation** | Cheap, recurring, insurance-required | Human risk + insurance |
| 6 | **Compliance readiness + vCISO** (HIPAA, SOC 2, NIST, PCI, multi-framework) | Enforcement up; 96% vCISO demand | Customer/contract/audit pressure |
| 7 | **Cloud management + cost optimization (FinOps)** across M365/Azure/AWS/GWS | Cost control + resilience | Bill shock, migration |
| 8 | **AI / automation (AIOps, workflow)** | Differentiator; 87% MSPs investing | Efficiency, labor cost |
| 9 | **Proactive managed IT + helpdesk (RMM, patching, monitoring)** | Baseline expectation | Outgrowing break-fix / no in-house IT |
| 10 | **Co-managed IT** (augment a 1-person internal team) | Dominant model 100–200 emp | Internal IT overloaded |
| 11 | **Network/firewall, infrastructure, procurement** | Necessary, less differentiating | Refresh, project, move |

---

## 3. Klaravex service-fit scorecard

**Legend:** ⭐ Lead-with (high demand + sticky + margin) · ✅ Sell (solid demand) · 🔁 Table-stakes (need it, don't differentiate) · 🧱 Commodity/project (lumpy, low recurring) · ❌ **GAP you don't currently offer**

| Klaravex service | SMB demand | Stickiness | Verdict |
|---|---|---|---|
| AI Workflow Automation / Loki | High & rising | High | ⭐ **Your #1 differentiator — lean on it everywhere** |
| Directive tier (compliance + vCISO + MDR-ish) | High | High (recurring) | ⭐ Lead the whole sales motion here (matches your GTM note) |
| Microsoft 365 mgmt + Entra/identity hardening | High | High | ⭐ Reframe around security/MFA, not just admin |
| IT Security Audit | High intent | Low (point-in-time) | ✅ Use as the **front door**, then convert to recurring |
| Backup & Disaster Recovery | High (insurance) | High | ✅ **Re-message as "immutable, tested, insurance-ready"** |
| Firewall & Network (UniFi + multi-vendor) | Medium-high | Medium | ✅ Bundle into managed plans |
| Microsoft Azure | Medium | High | ✅ Solid |
| AWS (new) | Medium-high | High | ✅ Multi-cloud moat |
| Google Workspace (new) | Medium (segments) | High | ✅ Owns startups/nonprofits/agencies |
| Intune / Endpoint Mgmt | High (insurance) | High | ✅ Pair with EDR (see gap) |
| Remote IT Support / Network Monitoring | Baseline | High | 🔁 Table-stakes — Loki + Atera deliver it |
| IT Strategy / vCIO | Medium-high | High | ✅ Strong in Directive; distinguish vCIO (ops) vs vCISO (security) |
| Penetration Testing | Medium | Low (project) | 🧱 Good credibility/lead item, lumpy revenue |
| Windows Server & AD | Declining (cloud shift) | Medium | 🧱 Necessary, not a growth story |
| Virtualization (VMware/Hyper-V) | Flat/declining | Medium | 🧱 Project work |
| PowerShell Automation | Low as standalone | Low | 🧱 Fold into AI Automation, not a headline service |
| IT Procurement | Low margin | Low | 🧱 Convenience add-on, never the pitch |

---

## 4. The gaps — what SMBs need that you're NOT selling (fix these)

These are the highest-demand, most insurance-driven, most recurring items, and your current catalog is **underweight on managed security operations.** This is the biggest strategic hole.

| ❌ Gap | Why it matters | How to add (lean) |
|---|---|---|
| **MDR / Managed Detection & Response (24/7)** | #1 SMB security spend; 71% adoption; insurers expect it | Partner/white-label an MDR/SOC (e.g. Blackpoint, Huntress, SentinelOne Vigilance) — don't build a SOC. Loki fronts triage. **Highest-priority addition.** |
| **EDR as a managed line** | Insurance non-negotiable on every endpoint/server | Resell + manage (Huntress/SentinelOne/Defender for Business). Pairs with Intune. |
| **Cyber-Insurance Readiness Assessment** | 73% fail; urgent, high-intent, deadline-driven | Package as a fixed-fee assessment → remediation retainer. **Best lead magnet you can build** — sharper than the generic free assessment. |
| **Security Awareness Training + phishing sim** | Insurance-required, recurring, cheap to deliver | Resell KnowBe4/Hook/usecure; pure-margin recurring revenue. |
| **Email security / anti-phishing** | #1 breach vector | Add to M365/GWS hardening as a managed add-on. |
| **Co-Managed IT offering** | Dominant model 100–200 emp | Define a "we augment your one IT person" SKU — bigger deals, less churn. |
| **vCISO (distinct from vCIO)** | 96% MSP demand; highest-value compliance clients | Split out security leadership as its own Directive-tier line. |

---

## 5. Recommendations

1. **Reposition the catalog around security + AI, not cloud admin.** The site currently reads "Microsoft shop that also does security." The market wants "AI-native managed security partner that also runs your cloud." Same services, reordered: lead with managed security + Loki, support with cloud/infrastructure.
2. **Close the MDR/EDR gap before launch.** It's the #1 SMB spend and the thing cyber insurance forces. Without a managed-security-operations answer, you're missing the largest, stickiest, fastest-growing budget line. White-label, don't build.
3. **Make "Cyber-Insurance Readiness" your lead magnet.** It's more urgent and higher-intent than a generic free assessment — there's a renewal deadline and a 73% failure rate driving the call. Funnels directly into remediation + a managed plan.
4. **Add the three pure-margin recurring lines:** security awareness training, email security, EDR. Cheap to deliver (resell), insurance-required, and they raise per-user value toward the $225–350 premium band.
5. **Re-tier with the gaps folded in, and raise Directive's ceiling:**
   - **Foundation $100/user** — managed IT, helpdesk (Loki+human), patching, M365/GWS admin, UniFi, MFA, backup. *(raise from $75 — you're under market)*
   - **Assurance $150–175** — + EDR, MDR, security awareness training, email security, immutable backup, security reviews.
   - **Directive $250–350** — + compliance readiness (HIPAA/SOC2/NIST/PCI), vCISO, board reporting, cyber-insurance readiness.
   - Add **Co-Managed IT** as a cross-tier option.
6. **Keep leading the sales conversation with Directive** (your existing GTM note is correct) — but Directive must visibly include managed security operations, or it won't justify $250–350.
7. **De-emphasize the commodity lines** (procurement, standalone PowerShell, legacy server/virtualization) on the site — keep them as capabilities, not headline services. They signal "break-fix shop," which fights your premium positioning.

**Bottom line:** Your list is strong on cloud + infrastructure and genuinely differentiated on AI (Loki). It is **underweight on managed security operations (MDR/EDR/awareness) and cyber-insurance readiness — which is exactly where the SMB money is moving and where insurers are forcing spend.** Close that gap (by partnering, not building), re-order the story around security + AI, and you match the 2026 SMB demand curve precisely.

---

## Sources
- [Integris — 10 MSP trends 2026](https://integrisit.com/blog/the-10-msp-trends-to-watch-in-2026-and-beyond/)
- [CIAOPS — MSP priorities 2026 (SMB)](https://blog.ciaops.com/2025/12/20/key-priorities-for-msps-in-2026-a-global-outlook-smb-focus/)
- [Digacore — what SMBs should outsource 2026](https://digacore.com/blog/managed-it-services-what-smbs-outsource-measure-improve/)
- [StationX — cybersecurity spending statistics 2026](https://app.stationx.net/articles/cybersecurity-spending-statistics)
- [StationX — small business cybersecurity statistics 2026](https://app.stationx.net/articles/small-business-cybersecurity-statistics)
- [Cyber Defense Magazine — state of SMB cybersecurity 2026](https://www.cyberdefensemagazine.com/the-state-of-smb-cybersecurity-in-2026-key-trends-and-predictions/)
- [Velocity Technology Group — cyber insurance requirements 2026](https://velocitytechnology.group/the-blog/cybersecurity-insurance-requirements-smb-guide/)
- [BASG — cyber insurance requirements 2026](https://basg.co/blog/cyber-insurance-requirements-2026-what-insurers-demand)
- [Hacker News / Cynomi — MSPs beyond vCISO tools](https://thehackernews.com/2026/06/the-security-growth-platform-why-msps.html)
- [Cynomi — compliance across overlapping frameworks](https://cynomi.com/blog/how-msps-deliver-compliance-across-overlapping-frameworks/)
- [DLCyber — SMB compliance guide NIST CSF 2.0/CCPA/SOC 2](https://dlcyber.com/blog/smb-compliance-guide-nist-csf-ccpa-soc2)
- [EFROS — vCISO for SMB pricing 2026](https://efros.com/resources/vciso-for-smb/)
- [ITBudgetCalculator — managed services cost 2026](https://itbudgetcalculator.com/managed-services-cost)
- [Corsica — managed IT services pricing 2026](https://corsicatech.com/blog/managed-it-services-pricing-cost/)
- [Medha Cloud — 48 SMB IT spending statistics 2026](https://medhacloud.com/blog/smb-it-spending-statistics-2026)
