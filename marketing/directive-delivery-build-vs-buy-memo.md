# Decision Memo — Directive-Tier Delivery: Build vs. Buy

**Prepared:** 2026-06-23 · **Scope:** US (klaravex.com) Directive tier delivery backbone · **Decision owner:** Anthony
**Status:** Analysis for decision. No commitment made. Figures are directional and must be validated with live partner quotes before any contract.

---

## 1. Executive Summary

The Directive tier you are now selling (readiness advisory + MDR + named vCISO) is **two delivery layers, not one**, and the two vendors on the table solve different layers:

- **Cynomi** = a vCISO / GRC / readiness platform (the *advisory and framework* layer).
- **Coro** = a security-controls / detection platform (the *MDR and protection* layer).

They are **complements, not substitutes.** "Cynomi vs. Coro" is the wrong question. The right question is build-vs-buy on each layer independently.

**Recommendation:** **Buy the readiness layer, buy the MDR layer, build the methodology and client relationship.** Specifically:

1. **Readiness/vCISO layer — BUY a platform (Cynomi is the lead candidate, but pilot before committing).** Building a multi-framework GRC engine and report generator in-house is a multi-quarter distraction from billable work, and the funded incumbents are years ahead. A platform turns one operator's time into senior-level deliverables at scale — which is the entire economic premise of the vCISO offer.
2. **MDR/protection layer — BUY a managed-detection stack, but do NOT assume Coro is automatically it.** Coro is a strong SMB security *platform* but its detection is largely automated/self-remediating, not a 24/7 human SOC. For a readiness-led brand selling to regulated verticals, a true MDR with human escalation (Coro is one option; Huntress, Blackpoint, SentinelOne+SOC are the realistic alternatives) may matter more than tool consolidation.
3. **Build nothing you can buy; own everything that's the moat** — the methodology, the vertical specialization, the client relationship, and the brand. Never resell a platform as "the product."

**Why not build:** A lean operator's scarcest asset is hours. Every hour spent building GRC tooling or a SOC is an hour not sold. Build-in-house only wins when the bought option can't deliver your differentiation — and here it can.

**The one real risk to manage:** platform lock-in and margin compression. Mitigations in §6–§7.

---

## 2. Reframe — the Directive tier is two layers

| Layer | What it does | What the client is buying | Candidate vendors |
|---|---|---|---|
| **L1 — Readiness / vCISO / GRC** | Risk assessment, framework mapping (HIPAA/SOC 2/ISO 27001/FTC), policy generation, executive reporting, roadmap | "Someone owns my security program and gets me audit-ready" | **Cynomi** (lead), Vanta/Drata (compliance automation, narrower), RealCISO, Centraleyes, or build |
| **L2 — MDR / protection** | Endpoint/email/network detection, monitoring, response, containment | "Someone is watching and will act when something happens" | **Coro** (platform/auto-remediation), Huntress, Blackpoint Cyber, SentinelOne + SOC, or build |
| **L3 — Methodology + relationship (the moat)** | Vertical expertise, the advisory judgment, the client trust, the brand | "I trust *Klaravex* specifically" | **Build / own — never outsource** |

You must source L1 and L2. L3 is non-negotiably in-house. The memo below decides L1 and L2.

---

## 3. Layer 1 (Readiness/vCISO) — options compared

| | **Build in-house** | **Buy: Cynomi** | **Buy: compliance-automation (Vanta/Drata)** |
|---|---|---|---|
| What you get | Your own templates, spreadsheets, manual framework mapping | AI-assisted assessment → 40+ frameworks in one pass, white-label exec reports, revenue-gap mapping, AI "CISO" agents | Strong SOC 2/ISO automation + auditor network; narrower framework breadth; built for end-cos, not MSP delivery |
| Time to first client deliverable | Weeks–months of unpaid build | Days (platform is turnkey) | Days–weeks |
| Multi-framework (HIPAA+SOC2+ISO+FTC) | You build each crosswalk by hand | Native, single assessment | Partial; HIPAA/FTC weaker than SOC 2/ISO |
| Built for MSP/multi-client delivery | N/A | Yes — purpose-built for service providers, white-label | Weaker; more single-org oriented |
| Cost (directional, **unverified**) | "Free" but consumes your billable hours | Est. low-five-figures/yr for a small license; per-client model; **opaque — get a quote** | Per-framework/per-entity SaaS; can run higher at multi-client scale |
| Known weakness | Slow, doesn't scale past your own hours, no AI leverage | Session-centric (one client context at a time, no portfolio dashboard); pricing opacity; packaging in flux (June 2026) | Self-serve DNA; not designed to deliver *as* a vCISO; you'd be bending a product to fit |

**Read:** Cynomi is the closest fit to a one-operator vCISO practice because it is explicitly built for service-provider delivery and white-labels to *your* brand (protects L3). Its session-centric architecture is a real limitation but only bites at ~10+ concurrent clients — not your near-term constraint. Vanta/Drata are better when the buyer is the end-company self-serving SOC 2; they're a poorer fit for *delivering* vCISO across mixed frameworks and verticals.

**Verdict L1:** **Buy. Pilot Cynomi first** (one real client engagement) before an annual commitment. Validate: actual price, portfolio-view pain, HIPAA/FTC depth (reviewers flagged niche-framework shallowness), and M365 integration depth (a flagged weakness).

---

## 4. Layer 2 (MDR/protection) — options compared

| | **Build (DIY stack + your own monitoring)** | **Buy: Coro** | **Buy: dedicated MDR (Huntress / Blackpoint / SentinelOne+SOC)** |
|---|---|---|---|
| Model | You assemble EDR/email/network tools + watch them yourself | Consolidated SMB platform, single agent, ~92% auto-remediation | 24/7 human SOC + analyst escalation on top of EDR |
| 24/7 human response | No — you're the on-call, which doesn't scale and is a liability | Largely automated; human SOC is partner/escalation-dependent | Yes — true human MDR is the product |
| Fit for readiness-led, regulated verticals | Weak — you can't credibly promise response coverage solo | Good for hygiene + consolidation; thinner on human escalation | Strongest — "someone is watching 24/7" is exactly the regulated-buyer promise |
| Cost (directional, **unverified**) | Tool licenses + your unpaid time | Partner-quoted (historically ~$9–10/user/mo entry; now quote-only) | Typically higher per-endpoint; SOC labor priced in |
| Known weakness | Single-operator response is the single biggest scaling risk you have | False-positive/alert-fatigue complaints; "limited response actions"; year-2 price jumps | Higher cost; another vendor relationship; less tool consolidation |

**Read:** This is the layer where "build" is most dangerous. A solo operator cannot credibly sell 24/7 detection-and-response to a medical or financial firm and *be* the response. That's an SLA and liability exposure, not a feature. The Directive promise ("someone is watching and will act") requires a real MDR behind it.

Coro is a legitimate option and pairs naturally with the SMB segment, but its strength is *consolidation and automation*, not human SOC depth. For regulated verticals where "we missed it / no one was watching" is a breach-and-lawsuit event, weigh a dedicated human MDR (Huntress and Blackpoint are the common lean-MSP choices) against Coro's platform model.

**Verdict L2:** **Buy MDR. Run a 2-way bake-off: Coro (consolidation play) vs. a human-SOC MDR (Huntress/Blackpoint).** Decide on the basis of human-escalation coverage and per-seat economics at Directive pricing — not on tool count.

---

## 5. Cost & margin model (illustrative — validate with quotes)

Directive tier lists at **$150–250/user/mo**. Illustrative blended cost-of-goods per user/mo, to be replaced with real quotes:

| Component | Est. cost/user/mo (**unverified**) |
|---|---|
| L1 readiness/vCISO platform (amortized per active user across book) | $3–8 |
| L2 MDR/security stack | $7–18 |
| Core managed-IT tooling (RMM/Atera, M365 mgmt, UniFi) | already in base tiers |
| **Est. platform COGS** | **~$10–26/user/mo** |

At $150–250 list, platform COGS of ~$10–26 leaves the gross margin to be consumed by **your labor**, which is the real cost and the real constraint. The platforms don't threaten margin; *your time per client* does. That is precisely why the buy-the-platform decision matters: AI-assisted readiness tooling is what lets one operator carry more Directive clients without linear time growth.

**Key margin insight:** Build-in-house looks "free" on this table because it has no license line — but it moves the cost into your unbilled hours, which is the most expensive and least scalable line you have. Buying is cheaper than building once your time is priced correctly.

---

## 6. Operational overhead, lock-in, exit risk

| Dimension | Assessment | Mitigation |
|---|---|---|
| **Vendor lock-in (L1)** | Cynomi holds your assessments/reports in its model; switching means re-platforming client programs | Keep a parallel export of every client's risk register, policies, and evidence in your own store (the klaravex repo / your DB) so the *system of record* is yours, not the vendor's |
| **Packaging instability** | Cynomi published a packaging change June 2026; price/tier risk on renewal | Negotiate a price lock at pilot→annual conversion; revisit annually |
| **MDR escalation gap** | If you buy Coro (auto-remediation) without human SOC, *you* are still the escalation point | Choose an MDR tier that includes human escalation, or pair Coro with a SOC service; don't sell 24/7 you can't staff |
| **Single-operator concentration** | Both platforms reduce but don't remove your personal bottleneck | Document runbooks; the platforms' white-label reporting is what lets a future hire or contractor step in |
| **Brand leakage (L3)** | Reselling a platform as "the product" cedes your moat | White-label everything; client never sees Cynomi/Coro branding; Klaravex owns the relationship and the deliverable |
| **note_submissions / routing** | This decision and any vendor onboarding are klaravex.com-surface actions → route to Azure `klaravex-db` per project rule | Log when executed; I have no DB write path in this session (flagged) |

---

## 7. Risks of getting this wrong

1. **Building the readiness layer** burns 1–2 quarters of billable capacity to reinvent what a funded vendor already ships — opportunity cost is the killer, not cash.
2. **Selling MDR you can't deliver** (solo "24/7") is an SLA/liability landmine in regulated verticals. The first missed incident is a breach *and* a malpractice conversation.
3. **Over-buying** (Cynomi + Coro + a separate SOC + Vanta) stacks COGS and complexity before you have the client volume to absorb it. Buy the minimum that lets you deliver the promise; add as the book grows.
4. **Letting a platform become the brand.** If clients learn they're "really" buying Cynomi/Coro, your pricing power and moat evaporate. White-label is non-negotiable.

---

## 8. Recommendation & phased path

**Decision:** Buy both layers, build the moat. Pilot before committing.

| Phase | Action | Gate to next |
|---|---|---|
| **0 — Validate (this month)** | Get live quotes from Cynomi (L1) and from Coro **and** one human-MDR (Huntress/Blackpoint) for L2. Connect Ahrefs/Similarweb separately for the content side. | Real numbers in hand |
| **1 — Pilot (1 client)** | Run one Directive engagement on Cynomi + chosen MDR. Measure: hours per client, deliverable quality, portfolio-view pain, escalation coverage. | Pilot proves margin + delivery |
| **2 — Commit** | Negotiate annual with price lock; stand up white-label reporting; mirror system-of-record into your own store. | Repeatable delivery |
| **3 — Scale** | Add clients; only then revisit Cynomi's portfolio-view limit and whether a second hire/contractor is needed. | ARR > threshold |

**Build only if** a pilot shows the bought platform can't carry your HIPAA/FTC vertical depth or can't white-label cleanly — neither is likely based on current evidence.

---

## 9. Open questions for Anthony (decision inputs)

1. **MDR philosophy:** do you want tool-consolidation (Coro) or human-SOC depth (Huntress/Blackpoint) as the L2 promise? This is the biggest open call and it's a positioning decision, not just a cost one.
2. **Capital posture:** is a low-five-figure annual platform commitment acceptable pre-revenue, or do you need per-client/pay-as-you-go until the first Directive deals close?
3. **White-label requirement:** confirm white-label is mandatory (recommended) so the brand decision is locked before any demo.
4. **Pilot client:** is there a current or near-term client to run the Phase-1 pilot on?

---

*Directional figures must be replaced with live quotes before any commitment. Cynomi and Coro pricing are both quote-only as of 2026-06-23. This memo decides delivery backbone only; it does not authorize spend.*
