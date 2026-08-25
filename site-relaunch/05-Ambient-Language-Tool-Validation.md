# Ambient Language Learning — Cheap Validation Kit
**Prepared:** 2026-06-03 · **Status:** Idea to validate BEFORE building · **Brand:** separate / "Labs," NOT on the Klaravex MSP site
**Decision on record:** validate cheaply now; do not build the product yet.

---

## 0. What this is (honest framing)
A **passive / ambient** language-immersion tool: it changes a small, growing share of the words in what you already read so you absorb a new language at the edge of attention — without it feeling like studying. Internal name for the concept: **"secondary"** (background) learning.

**The concept is validated but not novel.** Toucan (acquired by Babbel, 2022), Migaku, and LingQ already do word/phrase replacement and immersion. The swap is now trivial with an LLM. **So we are NOT testing "can we swap words" — we're testing one specific bet:**

> **Hypothesis:** Intermediate learners (and overwhelmed beginners) want a *gentler, adaptive, low-overwhelm* version that paces itself to them and works on phrases/grammar — not the beginner noun-swap most tools stop at. They'd join a waitlist / pay for that.

If that's false, kill it cheaply. If true, *then* scope a build.

**Reality checks baked in:**
- "Learn while you sleep" — weak evidence. Position around *awake, low-effort ambient* exposure, not sleep-osmosis.
- System-wide phone word-replacement is blocked by iOS sandboxing and Android Play policy. The viable surface is a **browser extension (desktop)** + your own reader app. Don't promise an OS-wide phone overlay.

---

## 1. Use Toucan for your own German — tonight, free
You described "an extension that changes words so I don't feel overwhelmed." That's Toucan, and it supports German.
1. Install Toucan (Chrome/Edge extension) → set target = German.
2. Set replacement frequency LOW to start (your low-overwhelm preference).
3. Browse normally for a week. Note precisely where it annoys or fails you (too random? only nouns? no phrases? bad pacing? no grammar?).
4. **Those gaps ARE your product spec.** You're now the sharpest tester of the wedge.
Also stack free ambient tactics: switch one device's UI to German, German podcasts at low volume while doing chores, German subtitles on shows you already watch.

---

## 2. The validation experiment (smoke test — ~$0–$50, ~a few hours)
**Goal:** prove demand without building the product.

**Build:** a single landing page + email waitlist (Carrd ~$19/yr, or a free Notion/Tally page; email via a free Mailchimp/Beehiiv tier). One page, one promise, one button.

**Drive cheap traffic (pick 2):**
- Reddit: r/languagelearning, r/German, r/Duolingo (post as a learner sharing the idea — read each sub's self-promo rules first; lead with the problem, not a pitch).
- A short post on your own LinkedIn (ties to your rebuild story).
- Comment helpfully in existing "Toucan is too random / I feel overwhelmed" threads.

**Measure ONE number:** email signups ÷ unique visitors (waitlist conversion).

**Decision thresholds:**
| Result | Read | Action |
|---|---|---|
| **≥ 8–10%** conversion + qualitative "yes, I'd pay" replies | Real signal | Scope a browser-extension MVP |
| **3–7%** | Lukewarm | Iterate the angle/segment once, retest |
| **< 3%** | No pull | Park it. You lost a weekend, not 6 months |

**Bonus signal:** add a "would you pay $X/mo?" question or a fake "Pre-order $5" button (Stripe) — *intent to pay* beats *intent to sign up* every time.

---

## 3. Landing page copy (paste into Carrd/Tally)

**Headline:** Learn a language in the background — without the overwhelm.

**Subhead:** Most apps make you sit down and grind. This one quietly changes a few words in what you already read, and grows with you — so you pick up a language at the edge of attention, not at a desk.

**The problem (3 lines):**
- Flashcard apps feel like homework, so you quit.
- Word-swap tools dump random nouns on you and overwhelm you.
- Nothing paces itself to *you* — or helps once you're past beginner.

**What we're building:**
- **Gentle by default** — starts with a trickle of words, grows only as you're ready.
- **Beyond nouns** — real phrases and grammar, for when "dog → Hund" stops being enough.
- **Adapts to you** — learns which words to introduce and which you've got.
- **Works where you already read** — your browser, on your schedule.

**The honest part (build trust):** No "learn while you sleep" magic. Just steady, low-effort exposure that actually fits a busy life.

**CTA:** `[ Join the waitlist ]`  ·  *optional:* `[ Reserve a spot — $5, fully refundable ]`

**Micro-question on the form:** "What language are you learning, and what's made you quit before?" (free-text — this is gold for the spec.)

---

## 4. What NOT to do yet
- Don't build the extension, the app, or the adaptive engine.
- Don't put it on klaravex.com (brand dilution — separate domain if it graduates).
- Don't spend on ads beyond a token test.
- Don't compete on the word-swap — that's commoditized. The bet is *pacing + intermediate + adapts-to-you*.

## 5. If it validates (≥ threshold) — the realistic MVP
- **Surface:** Chrome/Edge extension first (the only place the tech works cleanly).
- **Engine:** LLM-driven substitution that's grammar-aware + a spaced-exposure schedule (introduce/retire logic = the actual moat).
- **Wedge segment:** intermediate learners + overwhelm-averse beginners (you).
- **Then, maybe:** a mobile *reader* app (your content, where you control the text) — never an OS-wide overlay.
- Treat as a separate brand / "Klaravex Labs," funded only once the core business pays your bills.

---
*Sources: Toucan (Babbel) — word-replacement immersion, acquired 2022; Migaku; LingQ. The viable build surface is a desktop browser extension; iOS sandboxing and Android Play Accessibility-API policy block system-wide phone word replacement.*
