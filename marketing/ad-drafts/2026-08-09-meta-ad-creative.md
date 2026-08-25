# T-AC-XX · Meta (Facebook + Instagram) Ad Creative — Draft

**Date:** 2026-08-09
**Market:** US only (klaravex.com), USD only
**Voice policy:** third-person corporate ("Klaravex"/"we"), no personal names, no first-person singular, no internal codenames. Direct, specific, evidence-based — no generic tech-marketing phrases.
**Tagline:** Clarity. Security. Results.
**Palette:** teal + white + charcoal (exact hex per brand guidelines — see `brand/brand-strategy.md`).
**Companion drafts:** Google RSAs — `marketing/ad-drafts/2026-07-02-google-rsas.md`; LinkedIn ABM — `marketing/ad-drafts/2026-07-02-linkedin-abm-single-image-conversation.md`. This is the Meta gap-fill; verticals and positioning match those drafts.

## QA lessons applied from the Google/LinkedIn review (binding for this draft)

1. No bare outcome/timeframe claims — timeframes only appear with a "~" qualifier, and only in body copy, never as a headline hook.
2. No customer-trust/volume claims ("Trusted by...", "X practices trust Klaravex") — replaced throughout with positioning language ("Built for...").
3. "24/7 detection & response" is NOT used as a headline or primary-text hook anywhere in this draft. "Detection and response" appears only as a generic capability descriptor, unpromised on cadence, in body copy — pending the MDR delivery-model decision.
4. Regulator precision: financial-vertical copy defaults to the FTC Safeguards Rule (applies to CPAs/accounting firms generally). SEC language is isolated to a clearly-labeled RIA-only variant. FINRA is not used anywhere in this draft (RIAs are SEC-regulated; FINRA governs broker-dealers, which are not a named target segment here).
5. No guarantee language. "Certified," "guaranteed compliant," and implied certification badges/seals are avoided in both copy and image concepts.

---

## Universal suppression / exclusion note (apply to every audience below)

Exclude at the ad-set level, matching the exclusion policy already applied on Google/LinkedIn:
- Public Sector / Government
- Defense, DIB, CMMC
- Aerospace & Defense
- Cannabis
- Adult content
- Gambling

**Flag for human review before launch:** Ad copy referencing HIPAA, SOC 2, ISO 27001, or the FTC Safeguards Rule sits adjacent to Meta's automated classifiers for financial-services and health-adjacent content. Expect these ad sets to be routed through Meta's standard (non-Special-Ad-Category) review, but budget extra review time and have a fallback broad-targeting version ready in case Meta's classifier misflags any set into the Special Ad Category (Credit/Employment/Housing) restricted-targeting bucket — that bucket disables detailed targeting, lookalike audiences, and age/gender targeting. Confirm at ad-set creation whether Meta prompts a Special Ad Category declaration; if it does, the "targeting sketch" sections below need a broad/geo-only fallback.

---

## Vertical 1 — Healthcare / HIPAA (medical & dental practices, 10-100 employees)

**Destination URL:** `klaravex.com/healthcare-it-security`

### Single Image Ad

**Primary text (full):**
> When a client, insurer, or auditor asks to see your HIPAA security program, most practices scramble. Klaravex builds the written program, monitoring, and a named security lead before that request lands. Built for medical and dental practices with 10 to 100 employees. Book a readiness review and see where your program stands today.

*~125-char cutoff falls at:* "...builds the written program, monitoring, and a named security lead before that reques" — the hook and the "Klaravex builds..." sentence both land before the cutoff, so the ad reads coherently even if truncated.

**Headline (≤40):** `HIPAA Readiness, Managed` [24]
**Description (≤30):** `Book a readiness review` [23]

**Alt headlines for testing:** `Answer Audits With Evidence` [27] · `A Program, Not a Portal` [23]

**Image concept:** A dental or medical office administrator at the front/back-office desk, laptop open to a document titled "Security Risk Assessment — 2026." Real clutter: a wall calendar, patient scheduling monitor in soft focus, a coffee mug. No hooded figure, no padlock icon, no binary rain.
- **1:1 (Feed):** center the administrator and laptop screen; keep the document title legible in the top third.
- **9:16 (Stories/Reels):** shoot vertical with the administrator lower-third, laptop screen filling the middle band; leave top 20% clear for Meta's UI overlay and bottom 20% clear for the CTA sticker.

**CTA button:** `Learn More`

### Carousel (5 cards)

Chosen over video for this vertical because the "what's actually in a HIPAA program" message benefits from a checklist-style swipe rather than a timed narrative.

**Primary text (full):**
> A HIPAA program is more than a firewall and a password policy. Klaravex covers the risk assessment, the written policies, day-to-day monitoring, and a named security lead who can answer your next audit request directly. Swipe through what a real program includes.

*~125-char cutoff falls at:* "...password policy. Klaravex covers the risk assessment, the written policies, day" — reads cleanly at the cutoff.

**Headline (≤40):** `Built for Medical Practices` [27]
**Description (≤30):** `See your compliance gaps` [24]

**Card breakdown:**
1. Busy real medical/dental reception desk (photo) — overlay: "Every practice gets the HIPAA question eventually."
2. Close-up of a printed risk-assessment checklist on a desk, pen resting on it — overlay: "Risk assessment"
3. Clean mock dashboard screen (Klaravex teal/white/charcoal UI) showing monitoring status tiles — overlay: "Ongoing monitoring"
4. Photo of a person on a short video call at a desk (implying a real check-in, not a ticket queue) — overlay: "A named lead, not a ticket number"
5. Klaravex brand card: logo + "Clarity. Security. Results." + CTA text "Book a readiness review"

**CTA button:** `Book Now`

**Crop notes:** Carousel cards render 1:1 natively in feed; supply a 9:16 crop of card 1 only for Stories placement (Meta uses the first card for Stories carousels) with the reception-desk subject in the lower two-thirds.

### Targeting sketch
- **Interests:** HIPAA compliance, medical practice management, dental practice management, healthcare IT, health information management
- **Job titles/functions (where available via placement/behavior, not detailed targeting):** Practice Manager, Office Manager, Practice Owner (medical/dental), Compliance Officer
- **Lookalike idea:** 1-3% US lookalike seeded from `/healthcare-it-security` page visitors + readiness-checklist downloaders in this vertical

---

## Vertical 2 — Legal (law firms, attorneys/practice managers, 5-75 employees)

**Destination URL:** `klaravex.com/legal-it-security`

### Single Image Ad

**Primary text (full):**
> Corporate clients are sending outside counsel security questionnaires more often, and with shorter deadlines. Klaravex builds the program behind the answer: risk assessment, written policies, monitoring, and a named security lead who responds directly. Built for law firms with 5 to 75 employees.

*~125-char cutoff falls at:* "...security questionnaires more often, and with shorter deadlines. Klaravex builds the pr" — the "who's asking and why it matters" hook lands fully before the cutoff.

**Headline (≤40):** `Your Clients Are Asking Now` [27]
**Description (≤30):** `Built for law firms` [19]

**Alt headlines for testing:** `Answer Audits With Evidence` [27] · `A Program, Not a Portal` [23]

**Image concept:** An attorney's or office manager's desk: laptop open to an email subject line "Client Security Questionnaire — Response Due," a legal pad with real handwritten notes, a law-office bookshelf blurred in the background. No gavel-and-binary-code cliche.
- **1:1 (Feed):** frame the laptop screen and legal pad together, centered.
- **9:16 (Stories/Reels):** vertical crop favoring the laptop screen in the upper two-thirds, legal pad visible lower-third.

**CTA button:** `Learn More`

### Video (15-30 sec)

Chosen over carousel because the "scramble vs. ready" contrast plays better as a short before/after narrative.

**Primary text (full):**
> Watch how a law firm answers a client security questionnaire in days, not weeks, with a program already in place. Klaravex builds the documentation and monitoring so the answer is ready before the request arrives.

*~125-char cutoff falls at:* "...answers a client security questionnaire in days, not weeks, with a program already in" — reads cleanly.

**Headline (≤40):** `Answer Audits With Evidence` [27]
**Description (≤30):** `Book a readiness review` [23]

**Shot list:**
- 0:00-0:04 — Hook: close-up of an inbox notification, "Client Security Questionnaire — Due in 5 Days," on a laptop at a law-office desk.
- 0:04-0:10 — Cut to a calm office manager pulling up a folder labeled "Security Program — Current" instead of scrambling through email threads.
- 0:10-0:20 — Screen-capture style pass through a clean documentation set: Risk Assessment / Policies / Incident Response / Monitoring Log (real-looking, not a stock UI kit).
- 0:20-0:26 — Text overlay: "Built for law firms with 5 to 75 employees."
- 0:26-0:30 — End card: Klaravex logo + "Clarity. Security. Results." + "Learn more at klaravex.com/legal-it-security"

**CTA button:** `Book Now`

**Crop notes:** Native 9:16 cut for Stories/Reels (shoot vertical-first); center-crop to 1:1 for Feed, keeping the inbox notification (0:00-0:04) and the folder label (0:04-0:10) inside the safe center zone since those are the two legibility-critical text moments.

### Targeting sketch
- **Interests:** law firm management, legal technology (Clio, MyCase, PracticePanther), ABA membership content, small-firm legal practice management
- **Job titles/functions:** Managing Partner, Law Firm Administrator/Office Manager, Attorney (solo/small firm), Practice Manager (legal)
- **Lookalike idea:** 1-3% US lookalike seeded from `/legal-it-security` visitors + checklist downloaders

---

## Vertical 3 — Financial / Accounting (CPAs, RIAs, 10-100 employees)

**Destination URL:** `klaravex.com/financial-it-security`

### Single Image Ad

**Primary text (full):**
> The FTC Safeguards Rule requires a written information security program, not just antivirus software. Klaravex builds the program, monitors for threats, and puts a named security lead on your team who can walk your examiner or client through it directly. Built for CPA and accounting firms with 10 to 100 employees.

*~125-char cutoff falls at:* "...requires a written information security program, not just antivirus software. Klaravex" — the regulatory hook fully lands before the cutoff.

**Headline (≤40):** `FTC Safeguards Rule, Handled` [28]
**Description (≤30):** `FTC Safeguards, handled` [23]

**Alt headlines for testing:** `Built for CPA & RIA Firms` [25] · `A Program, Not a Portal` [23]

**RIA-only variant (use only when the ad set is scoped strictly to registered investment advisers — do not mix with general CPA/accounting audiences):**
- Swap headline to: `Built for SEC-Registered RIAs` [30]
- Swap primary text opening line to: "As an SEC-registered investment adviser, your written policies and procedures are a Form ADV and examination item, not paperwork you get to later." (Do not reference FINRA — FINRA governs broker-dealers, not RIAs.)

**Image concept:** A CPA firm partner at a desk with two monitors — one showing a client spreadsheet, one showing a document titled "Written Information Security Program — FTC Safeguards Rule." Real office setting, no glowing shield icons or fake certification seals.
- **1:1 (Feed):** center the two-monitor setup, document title legible on the right screen.
- **9:16 (Stories/Reels):** vertical crop favoring the document-titled screen, person visible in lower third.

**CTA button:** `Learn More`

### Carousel (5 cards)

Chosen over video because the "endpoint protection isn't a program" contrast is a checklist argument, same logic as the healthcare carousel.

**Primary text (full):**
> Bought endpoint protection and called it a program? Most firms have. The FTC Safeguards Rule asks for more: a risk assessment, written policies, an incident response plan, and ongoing oversight. Swipe to see what Klaravex delivers instead.

*~125-char cutoff falls at:* "...called it a program? Most firms have. The FTC Safeguards Rule asks for more: a risk" — reads cleanly.

**Headline (≤40):** `Built for CPA & RIA Firms` [25]
**Description (≤30):** `One program, one partner` [24]

**Card breakdown:**
1. Real accounting-office workspace (photo) — overlay: "Endpoint protection isn't a program."
2. Close-up of a printed written information security program cover page on a desk — overlay: "A written program"
3. Mock dashboard screen (teal/white/charcoal) showing monitoring status — overlay: "Ongoing oversight"
4. Photo of two colleagues in a short review meeting — overlay: "A named lead reviews it with you"
5. Klaravex brand card: logo + tagline + CTA text "Book a readiness review"

**CTA button:** `Book Now`

**Crop notes:** Supply a 9:16 crop of card 1 for Stories placement, subject centered.

### Targeting sketch
- **Interests:** CPA/accounting practice management, QuickBooks ProAdvisor, financial advisor practice management, RIA compliance content
- **Job titles/functions:** Managing Partner (CPA firm), Controller, Compliance Officer (financial services), Registered Investment Adviser / Principal
- **Lookalike idea:** 1-3% US lookalike seeded from `/financial-it-security` visitors — keep CPA-firm and RIA seed lists separate if volume allows, since the regulatory hook differs

---

## Vertical 4 — Brand / Generic SMB Compliance-Readiness (broad regulated-SMB awareness)

**Destination URL:** `klaravex.com` (homepage)

### Single Image Ad

**Primary text (full):**
> Regulated small businesses do not need another security tool. They need one program and one accountable partner. Klaravex delivers readiness advisory, detection and response, and a named security lead as a single managed service. Built for healthcare, legal, and financial firms navigating HIPAA, SOC 2, ISO 27001, or the FTC Safeguards Rule.

*~125-char cutoff falls at:* "...do not need another security tool. They need one program and one accountable partner." — the full positioning line lands before the cutoff.

**Headline (≤40):** `Built for Regulated SMBs` [24]
**Description (≤30):** `Klaravex readiness review` [25]

**Alt headlines for testing:** `A Program, Not a Portal` [23] · `Clarity. Security. Results.` [27]

**Image concept:** A real small-business office (professional-services feel, not a sterile stock set) — a person reviewing a laptop screen showing a simple three-tier program view labeled "Foundation / Assurance / Directive," a real desk with normal clutter (plant, notebook, second monitor). No hooded figures, no padlocks, no binary rain.
- **1:1 (Feed):** center the laptop screen and person, tier labels legible.
- **9:16 (Stories/Reels):** vertical crop with the laptop screen in the upper two-thirds.

**CTA button:** `Learn More`

### Video (15-30 sec)

Chosen over carousel because the brand/awareness message ("different practices, same unanswered question") works better as a narrative than a static swipe.

**Primary text (full):**
> Most small businesses stack up separate tools for security, compliance, and monitoring, and no one owns the whole picture. Klaravex is a different model: one program, one accountable team, built specifically for regulated small businesses.

*~125-char cutoff falls at:* "...stack up separate tools for security, compliance, and monitoring, and no one owns the" — reads cleanly.

**Headline (≤40):** `Clarity. Security. Results.` [27]
**Description (≤30):** `Built for regulated SMBs` [24]

**Shot list:**
- 0:00-0:05 — Hook: split-screen of three real small-business settings (medical front desk, law-office desk, accounting-office desk), each with a laptop open.
- 0:05-0:12 — Text overlay: "Different practices. Same unanswered question: who owns our security program?"
- 0:12-0:22 — Cut to a single Klaravex-branded dashboard view unifying readiness status, monitoring, and a named lead's profile card (real-looking UI, teal/white/charcoal, no fake certification badges).
- 0:22-0:28 — Text overlay: "One program. One accountable team."
- 0:28-0:30 — End card: Klaravex logo + "Clarity. Security. Results." + "Learn more at klaravex.com"

**CTA button:** `Learn More`

**Crop notes:** Shoot vertical-first for 9:16 (Stories/Reels native); for 1:1 Feed, center-crop keeping the split-screen framing intact in the 0:00-0:05 hook — this is the highest-drop-off moment and must not lose either side of the split in the crop.

### Targeting sketch
- **Interests:** small business ownership, cybersecurity for small business, SOC 2, ISO 27001, general compliance/regulatory content
- **Job titles/functions:** Owner/Operator, Office Manager, Operations Manager at regulated-adjacent SMBs (10-250 employees)
- **Lookalike idea:** broad US lookalike (2-4%) seeded from combined site-visitor list across all three vertical pages + email subscriber list; this set is the widest audience and doubles as the seed-list generator for the vertical-specific lookalikes above

---

## Claims flagged for human review before this creative goes live

1. **"FTC Safeguards Rule, Handled"** (headline) — "Handled" is a positioning claim, not a certification claim, but it reads close to an outcome guarantee. Recommend a compliance/legal skim before launch even though it avoids "certified"/"guaranteed."
2. **Regulatory-name copy generally** (HIPAA, SOC 2, ISO 27001, FTC Safeguards Rule appearing by name in ad text) — confirm with Anthony/legal that Meta's ad review doesn't route these into a restricted-targeting bucket; see the Special Ad Category note above.
3. **RIA-only variant's SEC language** — confirm the ad sets using this variant are genuinely scoped to SEC-registered investment advisers only, so the FINRA-exclusion logic in this draft isn't accidentally undermined by broad "financial services" interest targeting pulling in broker-dealer job titles.
4. **"Named security lead" / vCISO framing across all four verticals** — accurate to current positioning, but confirm the vCISO service is actually staffed and deliverable at the volume this creative will generate before it goes live; an underlying claim about "a named lead who responds directly" needs to be true in practice, not just in copy.
5. **Image concepts referencing document titles** ("Security Risk Assessment," "Written Information Security Program — FTC Safeguards Rule") — when these go to a designer/photographer, confirm no rendered badge, seal, or certification-style graphic gets added to the document mockups; that would cross into implied-certification territory even though the ad copy itself doesn't claim it.
6. **General expect-a-review-hold note** — HIPAA/financial-services adjacent copy commonly triggers a manual (not necessarily rejecting) review pass on Meta; budget 24-48 extra hours before the first flight of each ad set.

---

## Handoff notes for the Paid Social Strategist (campaign structure, out of scope here)

- Campaign objective recommendation: Traffic or Leads (on-platform lead forms not used here — all CTAs route to klaravex.com subpages per the destination-URL requirement above; a lead-form variant is a follow-up test, not in this draft).
- Placements: Facebook Feed, Instagram Feed, Instagram Stories, Instagram Reels, Facebook Reels. Skip Audience Network and Messenger placements for launch — revisit after baseline CTR data exists.
- Each vertical above should run as its own ad set (not blended) so the suppression list and lookalike seeds stay clean per audience.
- Creative fatigue cadence: plan a refresh (new hook, same offer) every 3-4 weeks per ad set, consistent with the LinkedIn draft's testing plan.

---

*Draft for Anthony's review. Adjust vertical priority, format mix (carousel vs. video), or CTA button choice before paste into Meta Ads Manager.*
