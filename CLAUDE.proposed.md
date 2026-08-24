# Klaravex — Corporate Voice & Positioning Policy

**Status:** Source of truth. The gatekeeper agent adjudicates every draft against this file. Where a stream charter and this file disagree, **this file wins** and the discrepancy is surfaced in the session report.

**Last decision date:** 2026-08-23
**Supersedes:** the 2026 brand-voice draft (healthcare/tech verticals, "Managed Security Provider", no pricing)

> **How to read this file.** It is not a brand-values document. It is a checkable specification. Every rule below is written so a rubric can return PASS or FAIL against it. If a statement here cannot be checked mechanically, it does not belong in this file.

---

## 1. What Klaravex is

Klaravex is a US managed security and network operations provider for small regulated professional practices. Klaravex designs and operates the network, runs the security stack across endpoints and cloud, and keeps the practice ready for the assessments its clients, insurers, and regulators will ask for.

**Category label (use verbatim):** managed security and network operations
**Do not use as the category:** managed IT · IT support · MSP · Managed Intelligence · AI-powered managed IT

*[Managed Intelligence is the Centered Networks category. Do not apply it to Klaravex without an explicit decision — see §9.]*

---

## 2. Target verticals — CHECKABLE LIST

Every prospect, persona, case study, and audience reference must fall inside this list.

**Primary**

| Vertical | Typical size | Primary driver |
|---|---|---|
| Small law firms | 5–50 | Client confidentiality, insurer requirements |
| Accounting practices | 5–50 | WISP obligation, client security reviews |
| Medical and dental offices | 5–50 | HIPAA readiness, patient data |
| Financial advisory firms | 5–50 | Regulator and custodian requirements |

**Secondary** — permitted, never the lead audience: architecture studios · real-estate brokerages · small technology companies pursuing SOC 2 or ISO 27001 readiness

**Excluded — automatic FAIL**
- Defense, DIB, CMMC, ITAR, or any government-classified adjacency
- Enterprise (500+ seats)
- Consumers — those belong to personal.klaravex.com, never to klaravex.com drafts

---

## 3. Product line — CHECKABLE LIST

### 3.1 Network & Infrastructure

Klaravex designs, installs, and operates the practice network. Two platform tracks, both first-class:

**Ubiquiti UniFi — the default for 5–50 seat practices.** Approved claims:
- Unified gateway, switching, wireless, Protect and Access from one controller
- Network segmentation and VLAN isolation — separating clinical, guest, and administrative traffic
- No per-feature subscription licensing on the network layer
- Centralized visibility across every site a practice runs
- A cost structure a practice of this size can actually carry

Positioning line: **enterprise-grade segmentation without enterprise licensing.**

**Palo Alto · FortiGate · Cisco — the enterprise firewall track.** For practices already running these platforms, multi-site deployments, or where an insurer or client requirement names them. Approved claims: next-generation firewall policy, deep packet inspection, site-to-site VPN, and centralized policy management.

Both tracks are approved product references. Neither is described as a downgrade from the other — platform selection follows the practice's size, existing estate, and requirements.

### 3.2 Cloud & Identity

Microsoft 365 and AWS administration, hardening, and monitoring. Identity and access management, conditional access, MFA enforcement, privileged access review, and offboarding controls.

### 3.3 Security operations

Endpoint detection and response · managed detection and response · continuous monitoring · incident response · access reviews · backup with verified restores · phishing simulation and staff training

### 3.4 Readiness and advisory

HIPAA readiness · SOC 2 readiness · ISO 27001 readiness · WISP drafting and maintenance for accounting practices · risk assessment and gap analysis · vCISO advisory

### 3.5 Healthcare IT security

A named service line on klaravex.com. Clinical and guest network separation, PHI access control and review, device inventory for clinical endpoints, and HIPAA readiness evidence maintained continuously. Medical and dental practices are a primary vertical (§2) — this line may lead a draft.

### 3.6 Named offers

| Offer | Role |
|---|---|
| **Readiness Review** | The entry offer. A scoped assessment of network segmentation, identity posture, endpoint coverage, backup state, and readiness gaps. Published on klaravex.com. Every draft with a CTA should route here unless the stream charter specifies otherwise. |

Offer names are fixed. Inventing an offer name is a FAIL.

## 4. Pricing — EXACT VALUES, AUTOMATIC FAIL IF VARIED

Official pricing, Anthony decision 2026-08-21. These are the only tier names and the only prices permitted in any draft.

| Tier | Price | Positioning |
|---|---|---|
| **Foundation** | **$49** per user/month | Network and endpoint baseline. Monitoring, patching, EDR, backup, MFA enforcement. |
| **Assurance** | **$79** per user/month | Foundation plus managed detection and response, access reviews, staff training. |
| **Directive** | **$129** per user/month | Assurance plus readiness programme, WISP maintenance, vCISO advisory, incident response retainer. |

Rules:
- Any other tier price is an automatic FAIL.
- Any other tier name is an automatic FAIL.
- Lead with the **Directive** value story — readiness, managed detection and response, vCISO. Never lead with price.
- "From $49 per user/month" is permitted as a floor reference. "$49 managed security" as a headline offer is not.

---

## 5. Voice — CHECKABLE RULES

| # | Rule | Check |
|---|---|---|
| V1 | Klaravex speaks as the corporation | No "I", "me", "my", "our founder". Use "we" / "Klaravex". |
| V2 | No personal names | "Anthony" or any founder name = FAIL |
| V3 | The AI is "Klaravex AI" or "our AI support coordinator" | The word "Loki" = FAIL |
| V4 | Concrete numbers | At least one exact, traceable figure per draft |
| V5 | CTA present | Points to klaravex.com or personal.klaravex.com. Forums exception: soft CTA on ≤1 of 3 replies, others `**CTA:** none` |
| V6 | Active voice, one idea per sentence | Sentences requiring a comma to survive should be two sentences |
| V7 | Specificity over adjectives | "VLAN isolation for clinical traffic" beats "robust security" |

### 5.1 Banned words and phrases — any occurrence is a FAIL

**"compliance"** — use *readiness*, *preparation*, or *advisory*. This applies to body copy, headings, titles, slugs, and filenames.

Abstractions: digital transformation · synergy · synergies · leverage · leveraging · empower · unleash · supercharge · revolutionize · seamless · cutting-edge · best-in-class · world-class · game-changing · holistic · journey

Punctuation: exclamation marks

### 5.2 Banned infrastructure vendor names — internal tooling, never client-facing

Hetzner · Azure · Atera · Vapi · Smartlead · Apollo · Higgsfield · ComfyUI · n8n

*Note: this bans naming Klaravex's own operational stack. Client-facing platforms Klaravex manages on a client's behalf — UniFi, Palo Alto, FortiGate, Cisco, Microsoft 365 — are approved product references under §3 and are not affected by this rule.*

### 5.3 Banned claims — automatic FAIL

- Any metric not traceable to `KLARAVEX_REAL_STATS` or to a source stated inside the draft
- Any resolution or uptime percentage without a stated denominator and period
- **"89% of IT issues resolved…"** — retired, unsubstantiated, do not reuse in any form
- Any claim of a committed German entity ("Klaravex GmbH coming soon", "our Berlin office")
- Any headcount, team-size, or "our engineers" plural claim that the Impressum and Handelsregister would not support
- Defense, DIB, or CMMC capability or targeting

---

## 6. Messaging pillars

**1 — The network is the control.** Most small practices have flat networks. Every device sees every other device. Segmentation is the single highest-value change most practices can make, and UniFi makes it affordable at their size.

**2 — Readiness is a state, not an event.** Passing an assessment once is not the goal. Klaravex operates the controls continuously and keeps the evidence current, so the answer exists before the question arrives.

**3 — Detection, not just prevention.** Prevention fails eventually. Managed detection and response is the difference between an incident and a breach notification.

**4 — Sized for the practice.** Enterprise security programmes do not scale down. Klaravex builds for 5–50 seats, with a cost structure a practice of that size can carry.

---

## 7. Audience-specific framing

| Audience | Lead with | Avoid |
|---|---|---|
| Law firms | Client confidentiality, insurer requirements, matter data segregation | Framework acronyms in the opening line |
| Accounting practices | WISP obligation, client security reviews, busy-season uptime | Anything implying tax or advisory expertise |
| Medical and dental | Patient data, HIPAA readiness, clinical/guest network separation | Clinical workflow advice |
| Financial advisory | Custodian and regulator requirements, evidence on demand | Investment or market commentary |
| Practice owners | Business risk, cost predictability, time not spent on this | Deep technical detail |
| Office IT contacts | Segmentation design, UniFi controller topology, EDR coverage, access reviews | Oversimplification |

---

## 8. Website alignment — OPEN ACTIONS

The live site does not match this file. Until these are closed, drafts follow **this file**, not the site.

| # | Item | Action |
|---|---|---|
| 1 | UniFi absent from klaravex.com | **Add** as a first-class pillar per §3.1. Palo Alto / FortiGate / Cisco stay — UniFi is an addition to the product line, not a replacement. |
| 2 | "89% of IT issues resolved before you finish your coffee" still live | Remove — violates §5.3 |
| 3 | "Managed IT & Security — AI-Powered" | Replace with the §1 category label |
| 4 | Verticals listed as accounting, advisory, architecture, real estate | Align to §2 — law and medical are primary and currently missing |
| 5 | Only "from $49" shown | Publish the full Foundation / Assurance / Directive ladder per §4 |
| 6 | Sheridan, Wyoming registered-agent address | Remove wherever it appears `[CONFIRM with counsel]` |
| 7 | "engineers average twelve years" | Rephrase to comply with §5.3 |

---

## 9. Open decisions — DO NOT ASSERT UNTIL RESOLVED

Drafts must not make claims in these areas until a decision is recorded here.

1. **Relationship to Centered Networks.** Sister practice, parent, or unrelated? Until decided, no draft may reference Centered Networks, its Microsoft Solutions Partner designations, or its client list.
2. **Klaravex.de / EU operation.** No German entity claims permitted (§5.3). The relationship between klaravex.com and klaravex.de is undecided.
3. **Whether SOC 2 / ISO 27001 readiness for technology companies is a primary or secondary motion.** Currently secondary (§2).
4. **Named client references.** No client may be named in any draft until naming rights are confirmed in writing.

---

## 10. Change control

This file is the authority the gatekeeper enforces. A change here changes what publishes, without further human review.

- Record the decision date on every substantive change.
- Pricing changes require an explicit dated decision line, as in §4.
- Adding a vertical, a product pillar, or an approved claim requires updating the checkable list in §2 or §3 — the gatekeeper cannot enforce what is not listed.
- After any change, re-run the gatekeeper across ungated drafts before the next publish cycle.
