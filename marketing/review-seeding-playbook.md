<!--
PROCESS DOC — Review-seeding playbook (US / klaravex.com). Executable as a process; cannot generate reviews
(those require real clients). Voice policy applies to any client-facing template text below.
Prepared 2026-06-23.
-->

# Review-Seeding Playbook — Building Third-Party Proof

**Why this matters (from the competitive brief):** Ntiva has ~1 G2 review for its scale; the platform competitors lean on self-issued seals. Real third-party reviews on Clutch and G2 are cheap, durable differentiation in a market where buyers run comparison processes. The constraint: reviews must come from real clients — this is a *process*, not content I can generate.

---

## 1. Objective & targets

| Metric | 90-day target | Why |
|---|---|---|
| Clutch reviews | 2–3 | Clutch verifies via interview → high-trust; formation checklist gates paid evaluation at 2–3 reviews |
| G2 reviews | 3–5 | Shows up in buyer comparison processes; counters competitors' thin presence |
| Google Business Profile reviews | 5+ | Local trust + SEO; lowest friction for clients |

**Sequence:** Google Business Profile first (lowest friction) → Clutch (highest trust) → G2 (comparison surface). Don't ask one client for all three at once.

---

## 2. Who to ask (and when)

Ask only clients where you've delivered a clear, nameable win. Best moments to ask:

- Right after a **successful readiness milestone** (passed a Stage 1 audit, completed a HIPAA risk analysis, cleared a client security questionnaire).
- After you **resolved an incident** cleanly.
- At a **positive QBR** or renewal.

Avoid asking during an open issue, mid-escalation, or in the first 30 days of an engagement.

**Prioritize** clients who: are in a named vertical (healthcare/legal/financial — their review doubles as vertical proof), are articulate, and have a title that lends credibility (owner, managing partner, practice administrator).

---

## 3. The ask (templates — voice-policy compliant)

**A) Soft warm-up (in a QBR or call), verbal:**
> "We're starting to share client experiences publicly. If you've been happy with the work, would you be open to a short review? I can send a direct link — it takes about five minutes."

Get a yes *before* sending anything.

**B) Email — Google Business Profile (lowest friction):**
> Subject: A quick favor — 5 minutes?
>
> Hi [First name],
>
> It's been a pleasure getting [Practice/Firm] to a stronger security footing. If you'd be willing to share a short note about your experience, it genuinely helps other [medical practices / law firms / advisory firms] find us.
>
> Here's a direct link: [Google review link]
>
> No pressure at all — and thank you either way.
>
> — Klaravex

**C) Email — Clutch (higher effort, set expectations):**
> Subject: Would you be open to a short Clutch interview?
>
> Hi [First name],
>
> Clutch is an independent B2B review platform — they verify reviews with a brief (15-minute) interview, which is why buyers trust them. Would you be open to a quick call with them about your experience with Klaravex?
>
> If yes, I'll send the invite and they'll coordinate directly. Thank you for considering it.
>
> — Klaravex

**D) Email — G2:**
> Subject: A quick G2 review?
>
> Hi [First name],
>
> If you've found our work valuable, a short G2 review helps other firms evaluating security partners. Direct link here: [G2 link]. Five minutes, and it makes a real difference. Thank you.
>
> — Klaravex

**Prompts to offer (so the client isn't staring at a blank box):**
- What problem were you facing before Klaravex?
- What did we deliver, specifically?
- What's different now (an outcome, a number, an audit passed)?
- Would you recommend us, and to whom?

---

## 4. Guardrails (compliance & platform rules)

- **Never offer compensation or incentives for reviews** — violates G2/Clutch/Google policies and FTC endorsement rules. Reviews must be unsolicited-in-substance and voluntary.
- **Don't write the review for them.** Offer prompts, not text.
- **Don't bulk-ask.** Stagger requests; a sudden spike of reviews looks manufactured and can be filtered.
- **Confidentiality:** healthcare/legal/financial clients may be sensitive about being named. Offer the option to review without disclosing specifics of their environment. Never include PHI, matter details, or client financial specifics in any review prompt.
- **Respond to every review** (positive or critical) professionally, as Klaravex — never defensively.

---

## 5. Tracking (simple, do it in the repo or a sheet)

| Client | Vertical | Win to cite | Asked (date) | Platform | Status | Live URL |
|---|---|---|---|---|---|---|
| … | … | … | … | GBP/Clutch/G2 | asked / in progress / live | … |

Cadence: review the tracker monthly; target one new ask per closed milestone.

---

## 6. Directory priorities (from formation checklist)

First wave (free, high-intent): **Google Business Profile, Clutch, G2.**
Compliance-buyer intent (high value): **Vanta Partners directory, Drata Partners directory** — list once partner status is established.
Second wave: GoodFirms, UpCity, MSPAlliance, CompTIA locator.

---

## Notes
- This is process only — execution requires real clients and their consent.
- Routing: review-seeding for klaravex.com surface → Azure `klaravex-db` per project rule (log when executed).
