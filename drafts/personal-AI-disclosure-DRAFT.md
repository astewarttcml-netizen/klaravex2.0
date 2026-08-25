# DRAFT — AI-Delivery Disclosure for personal.klaravex.com

**Status:** Draft for review. Not published. Legal sign-off on the DSGVO/remote-access notice still required before German consumer traffic.
**Goal:** Reconcile the consumer site's "real experts" framing with the AI-delivery reality already disclosed on klaravex.com, satisfying FTC (US) and EU AI Act Art. 50 transparency expectations.

---

## The problem this fixes

The current consumer copy implies human-only delivery ("real help from real experts," "someone who genuinely helped"). klaravex.com discloses AI-first delivery ("89% resolved by AI"). The two properties contradict each other. This block makes the consumer story honest and turns the AI into a trust asset instead of a liability.

---

## ⚠️ READ FIRST — Phase-matched disclosure

Disclosure must match how the service is **actually delivered today**, not the end-state. Using the wrong phase's language is itself a misrepresentation.

| Phase | Delivery reality | Disclosure to use |
|---|---|---|
| **Phase 1 — trust-building (current)** | Human (you) handles/reviews **every** case; AI assists behind the scenes | **Light assist-disclosure** (below). "Real experts" framing stays — it's accurate. |
| **Phase 2 — graduated autonomy** | Agents resolve some categories **without per-case review**; humans escalate | **Full AI-delivery band** (Options 1–3 below). |

**The dividing line is supervision, not technology.** As long as a certified human approves every customer-facing outcome, the service is human-delivered and Phase-1 disclosure suffices. The moment an agent resolves a case the customer acts on **without your review**, Phase-2 disclosure becomes mandatory (FTC / EU AI Act Art. 50).

Do **not** deploy the Phase-2 band while you're still in the loop on everything — it overclaims AI involvement and undersells that you're personally doing the work.

### Phase 1 — assist-disclosure line (use now)

Add one honest line near the hero or in "How it works." Truthful, light, no overclaim:

> *We use AI tools to work faster — but a real, certified expert personally handles your request, every time.*

Or, slightly warmer for the consumer audience:

> *Yes, we use smart AI tools to move quickly. No, you're never handed off to a bot — a real person handles and checks everything you get from us.*

Nothing else on the current site needs to change in Phase 1. The "real experts" headline, the testimonials, and the human "How it works" steps are all accurate while you supervise every case.

### Phase 2 — full AI-delivery disclosure

When agents graduate to unsupervised resolution (see graduation criteria at end), switch to Options 1–3 below. These are the **Phase-2** strings — hold them until then.

---

## Option 1 — Hero sub-headline replacement (minimal, highest visibility)

> **Current:** "Plain English. No jargon. No judgment. Whether it's fixing a frustrating problem, protecting your family online, or finally learning to use AI — we've got you."

> **Draft replacement:**
> Plain English. No jargon. No judgment. Our AI assistant handles most requests instantly, any hour — and a real, certified expert steps in the moment your problem needs a human. You'll always know which one you're talking to.

---

## Option 2 — Dedicated disclosure band (recommended — place directly under hero)

> ### AI-fast, human-backed — and always labeled.
> Most everyday tech problems get solved instantly by our AI assistant, 24/7. When something needs real judgment — a tricky repair, a security worry, a patient walkthrough — a certified human expert takes over with the full history already in hand.
>
> **You're never left guessing.** Every message is clearly marked AI or human. No pretending, no bots posing as people.

This mirrors klaravex.com's "AI first. Humans when it matters." language so both sites tell one story.

---

## Option 3 — "How it works" step revision (fixes the implied-human flow)

The current Step 2 ("We fix it together… Remote session via screen share") reads as human-only. Suggested revision:

> **2 · We solve it — AI first, human when it counts**
> Our AI assistant starts working on your problem right away and resolves most issues on the spot. If it needs a person, a certified expert takes over — same conversation, full context, no starting over. We always tell you who you're working with.

---

## Required supporting elements (not optional)

| Element | Where | Why |
|---|---|---|
| One-line AI disclosure | Hero or band (above the fold) | EU AI Act Art. 50 / FTC: disclosure must be visible *before* the user engages, not buried in ToS |
| "AI vs. human" labeling promise | Disclosure band + live chat UI | The labeling claim must be true in the actual product, not just on the marketing page |
| Privacy / remote-access processing notice | Linked from footer | DSGVO Art. 13 — agents accessing a device process personal data; needs lawful basis + notice. **Legal to confirm.** |
| Disclosure in ad copy | Every platform listing (Kleinanzeigen, Thumbtack, LSA, GBP) | Platforms review the listing, not your site — disclosure must travel into the ad text |

---

## Testimonial caution

Three testimonials ("someone who genuinely helped," "patient and kind") read as human-delivered. If the work was AI-assisted, leaving them unqualified undercuts the disclosure. Either (a) confirm these reflect human-handled cases, or (b) add a light "AI + expert" attribution so the social proof matches the disclosed model.

---

---

## Graduation criteria — moving a task from supervised (Phase 1) to autonomous (Phase 2)

Trust isn't a feeling; it's a threshold you define in advance so Phase 1 doesn't silently become permanent. Graduate **one task category at a time**, not the whole service at once.

### Per-category graduation gate

A task category (e.g., "password reset," "Wi-Fi reconnect," "printer driver fix") moves from supervised → autonomous only when **all** of these are true:

| Gate | Threshold (starting point — tune to your risk tolerance) |
|---|---|
| **Volume** | ≥ 30 supervised cases in that category |
| **Accuracy** | ≥ 95% resolved correctly on first attempt, judged by you |
| **Zero-harm record** | 0 cases that caused data loss, security exposure, or required rework |
| **Customer-safe blast radius** | Worst-case failure is reversible and non-damaging (rules out anything touching backups, payments, security config, data deletion) |
| **Escalation works** | Agent reliably recognizes its own edge cases and hands off, demonstrated across the sample |

### Tiering by risk — what graduates early vs. never

| Tier | Examples | Autonomy path |
|---|---|---|
| **Green — graduate first** | Password resets, Wi-Fi reconnect, app reinstall, printer drivers, "how do I" questions | Eligible for full autonomy once gate is met |
| **Yellow — graduate late, with guardrails** | Email/account setup, software config, privacy settings | Autonomous *draft*, human approves before it reaches the customer |
| **Red — never fully autonomous** | Data recovery, security incidents, anything touching backups/payments/identity, senior/vulnerable customers | Human-in-loop permanently, regardless of agent track record |

### Operational discipline

- **Log every supervised case** with category + outcome from day one, or you'll have no data to graduate on.
- **Review weekly:** which categories are approaching the gate? Which agents are mis-escalating?
- **One-way door protection:** a graduated category that produces *any* harmful failure drops back to supervised immediately. Trust is revocable.
- **Disclosure flips per category:** the moment *any* category goes autonomous, the site needs Phase-2 disclosure — even if 90% of work is still supervised. You can't be "a little bit autonomous" without disclosing it.

### The exit-criteria warning

Define these thresholds **now**, before Phase 1 starts. Without them, "I'll automate when I trust it" has no finish line — you stay personally on every ticket, the timezone/capacity ceiling the agents were meant to remove comes back, and you've built a job instead of a business. The graduation gate is what makes Phase 1 a *phase* and not a permanent state.

---

## What I did NOT change
Nothing on the live site. These are replacement-candidate strings and an internal operating framework for your review only.
