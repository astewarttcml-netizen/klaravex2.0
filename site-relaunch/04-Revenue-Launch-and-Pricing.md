# Klaravex — Revenue Launch, Consumer Pricing & Page Template
**Prepared:** 2026-06-03 · Companion to `01-Migration-and-Expansion-Plan.md` and `02-Content-Drafts.md`

---

## PART 1 — Week-One Revenue Sequence (cash-now focus)

You need income while the MSP pipeline builds. Rank by **time-to-first-dollar**, not by long-term value. Stand these up in order.

### Tier A — launch in days, zero infrastructure (do these FIRST)
| # | Offering | Why it's fast | First-dollar path |
|---|---|---|---|
| 1 | **Resume & Job-Search Help** | You've lived the job hunt; only needs a doc template + intake form | Post your story + offer on LinkedIn; 1 free resume review → paid rewrite |
| 2 | **AI Skills Coaching** | Pure expertise + a video call; no tooling | Same LinkedIn audience; "30-min AI-for-job-search" paid sessions |
| 3 | **Job-Hunt Tech Kit** | You do this in your sleep (domain/email/site/LinkedIn/AV) | Bundle-sell to resume clients as an add-on |

These three share one audience (job seekers), one channel (LinkedIn + your own story), and one intake form. Build that once, sell all three.

### Tier B — launch in ~1–2 weeks, light setup
| # | Offering | Setup needed |
|---|---|---|
| 4 | **Personal IT Help** (per-incident) | Zoho Assist link + Stripe/payment + booking |
| 5 | **Solo-Business Launch Kit** | Same skillset as #3, scoped bigger; feeds B2B |
| 6 | **Identity & Data Cleanup / Privacy** | Checklist + Stripe; mostly your time |

### Tier C — recurring revenue, build after A/B are earning
- Klaravex Home membership ($24/mo), Family/Senior ($19/mo) — recurring, but needs the per-incident flow proven first.
- B2B managed plans — highest value, longest sales cycle; keep prospecting in parallel.

### The one funnel that ties it together
**Your story → LinkedIn post → free resume review → paid resume → add Tech Kit / Coaching → (if they're going solo) Launch Kit → (if they incorporate) B2B client.** Every consumer entry point has an upgrade path, ending in recurring B2B revenue.

### First 7 days, concretely
1. **Day 1–2:** Stripe account + one booking link (Calendly) + a simple intake form. Resume + Coaching only.
2. **Day 2–3:** Publish `/personal/resume-job-search/`, `/personal/ai-skills-coaching/`, `/personal/job-hunt-tech-kit/` (drafts already written, §02 D3/D10/D5).
3. **Day 3:** Post your founder story on LinkedIn with a clear offer (free resume review, limited slots).
4. **Day 4–7:** Deliver free reviews → convert to paid. Stand up Personal IT Help (Zoho Assist) in parallel.

> Keep logging your own relocation/restart costs (see `03`). Separate track, but don't lose the records.

---

## PART 2 — Consumer Pricing Page  (/personal/pricing/)

**Title:** Personal Help — Simple, Honest Pricing | Klaravex
**H1:** Clear prices. No surprises. You only pay once we know what's wrong.

*Fast-revenue lines pulled to the top intentionally.*

### Career & Fresh-Start Help
| Service | Price | What you get |
|---|---|---|
| **Free Resume Review** | **$0** | Honest 15-min review + what to fix. No catch. |
| **ATS-Optimized Resume** | **$199–$499** | AI beats the screener; a human makes you the candidate. By career level. |
| **LinkedIn Optimization** | **+$99–$199** | Get found by recruiters, not buried. |
| **Full Job-Search Package** | **$499–$799** | Resume + LinkedIn + cover letters + interview coaching + search strategy. *60-day interview guarantee or free rewrite.* |
| **Job-Hunt Tech Kit** | **$199–$399** | Domain, pro email, portfolio site, LinkedIn, interview-ready camera setup. |
| **AI Skills Coaching** | **$75/session · $199 starter (3 sessions)** | Use AI for your job search, writing, and admin. |
| **Solo-Business Launch Kit** | **$299–$599** | Going independent? Online, secure, and invoicing in a weekend. |

### Everyday Tech Help
| Service | Price | What you get |
|---|---|---|
| **One-Time Fix** | **from $79** | Flat per issue, quoted before we start. |
| **Klaravex Home Membership** | **$24/mo** | 24/7 AI help, priority human support, covered sessions monthly, whole household. |
| **Family & Senior Tech + Scam-Proofing** | **$19/mo** | Devices locked down, a 24/7 "is this a scam?" line, patient help. |

### Online Safety
| Service | Price | What you get |
|---|---|---|
| **Identity & Data Cleanup** | **from $149** | Post-breach lockdown: credit freezes, 2FA, password manager, monitoring. *(Security setup — not credit repair.)* |
| **Privacy / "Delete Me"** | **from $129 + $9/mo** | Get your info off people-search sites; ongoing re-removal. |
| **Scam & Fraud Recovery Support** | **Free** | Secure your accounts, organize evidence, understand your options. *(Gated until E&O + counsel review.)* |

**Every engagement:** you start the session (we never cold-call), you watch your screen, you get a written summary, no payment before diagnosis. `[Book now →]` `[Free resume review →]`

---

## PART 3 — Phase-0 Service-Page Template (give to Loki as the master pattern)

**Purpose:** every B2B service page (the 14 ported + 3 new) uses this exact structure so the site stops looking inconsistent. Loki fills the bracketed slots; never reorders sections.

```
[H1] — Outcome-first headline (what the client gets, not the tech name)
       e.g. "Microsoft 365, run right — so your email, files, and team just work."

[Intro · 2–3 sentences] — The problem in the client's words + the promise.
       Plain English. No vendor jargon in the first line.

[Section: "What's included"] — 4–6 bullets, each = capability + benefit
       • [Capability] — [why it matters to them]

[Section: "Who this is for"] — 1–2 lines naming the buyer
       e.g. "5–50 person firms with no in-house IT and real uptime needs."

[AI note · 1 line] — How Loki + human escalation applies here.
       "Loki monitors this 24/7 and flags issues instantly — a senior engineer
        acts on anything serious."

[Section: "What good looks like"] — 1 outcome/proof point (US-framed, anonymized)
       e.g. "A 28-user firm migrated in one week, zero data loss."

[FAQ · 3 questions] — the real objections (price model, lock-in, transition risk)

[CTA block] — "[Get a Free IT Assessment →]"  + secondary "[See pricing →]"

[Footer microcopy] — "No vendor commissions, ever. US-based, remote-first."
```

**Build rules for Loki (enforce):**
1. Apply the Americanization find-and-replace (§02 E) to every page before publishing.
2. Build as **DRAFT**, never live-edit a published page.
3. Use only prices from `02-Content-Drafts.md`; do not invent numbers.
4. One AI note per page — transparent, never implying Loki is human.
5. US spelling, USD, "readiness/advisory" not "compliance" in marketing.
6. Every nav link must resolve to a real page — no "coming soon."

**Validation gate before publish:** grep the page for `€`, `NIS2`, `DSGVO`, `Berlin`, `optimise`, `centre` → must be zero hits.
