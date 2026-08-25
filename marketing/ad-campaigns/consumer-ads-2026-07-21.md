# Ads Campaign Architecture — Klaravex Consumer (personal.klaravex.com)
**Task:** T-AC-09 | **Revised:** 2026-07-21 | **Status:** READY TO LAUNCH

---

## Strategy

**Product:** $29 flat-rate remote IT support session — no time limit
**Target:** US consumers with an active computer problem
**Budget:** $500/month split across Google, Meta, LinkedIn
**Goal:** Paying sessions booked via personal.klaravex.com

---

## Budget Allocation

| Channel | Monthly | Daily | Why |
|---------|---------|-------|-----|
| **Google Search** | $300 | $10 | Highest intent — people searching for help now |
| **Meta (FB/IG)** | $150 | $5 | Retargeting + awareness, 35-65 audience |
| **LinkedIn** | $50 | ~$1.70 | Professional audience, "my work laptop is slow" |
| **TOTAL** | **$500** | **~$16.70** | |

Scale trigger: raise budget when CPA < $15 sustained over 7 days.

---

## Channel 1: Google Search — $300/month

### Campaign: "KLX-Consumer-Search"
**Bidding:** Maximize conversions (switch to Target CPA $15 after 15 conversions)
**Geo:** United States (all)
**Device:** All (mobile priority — people search on their phone when computer is broken)
**Schedule:** 24/7

### Ad Group 1 — Computer Problems (highest volume)
**Keywords (phrase match):**
- "computer running slow"
- "fix my laptop"
- "my computer is slow"
- "computer repair near me"
- "laptop repair online"
- "remote computer help"
- "computer help online"

### Ad Group 2 — Virus / Security
**Keywords (phrase match):**
- "virus removal"
- "malware removal"
- "computer virus help"
- "my computer has a virus"
- "remove malware from computer"

### Ad Group 3 — Specific Problems
**Keywords (phrase match):**
- "computer won't start"
- "laptop screen black"
- "wifi not working"
- "printer not working"
- "email not working"
- "computer freezing"
- "blue screen fix"

### Ad Group 4 — Brand / Direct
**Keywords (exact match):**
- [klaravex]
- [klaravex support]
- [remote IT support $29]

### Negative Keywords
- free
- download
- software
- tutorial
- how to (broad)
- DIY
- reddit
- youtube
- class
- course
- certification
- jobs
- hiring
- salary
- enterprise
- business (add only if consumer intent suffers)

### RSA Ad Copy (all ad groups share)

**Headlines (max 30 chars each):**
1. $29. Fixed. No Catch.
2. Your IT Guy Charges What?
3. Geek Squad Can Wait
4. We Fix It. You Watch. $29.
5. Stop Googling. We'll Fix It.
6. $29 and Your Laptop Lives
7. Faster Than Your Nephew
8. No Drive. No Wait. $29.
9. Your Printer Hates You Too
10. $29 Virus Exorcism
11. We See Your Screen. We Fix.
12. Cheaper Than a Pizza + Tip
13. AI Finds It. Human Fixes It.
14. It's $29. Just Do It.
15. Still Restarting? Call Us.

**Descriptions (max 90 chars each):**
1. We remote into your computer and fix it while you watch. $29. No time limit. No upsell.
2. Our AI finds the problem in 6 minutes. A real engineer fixes it. You stay on your couch.
3. Geek Squad wants $200 and your laptop for a week. We want $29 and 20 minutes. Your call.
4. Slow laptop? Virus? Printer rebellion? $29 flat. We've seen worse. We've fixed worse.

**Final URL:** `https://personal.klaravex.com/?utm_source=google&utm_medium=cpc&utm_campaign=consumer-search`

**Sitelink Extensions:**
- "How It Works" → personal.klaravex.com/how-it-works
- "Pricing — $29 Flat" → personal.klaravex.com/pricing
- "Virus Removal" → personal.klaravex.com/services/virus-removal
- "Slow Computer Fix" → personal.klaravex.com/services/slow-computer

**Callout Extensions:**
- No Time Limit
- $29 Flat Rate
- AI-Powered Diagnosis
- Mac & PC
- Remote — No Travel

**Call Extension:** +1(424)348-6010

---

## Channel 2: Meta (Facebook + Instagram) — $150/month

### Campaign: "KLX-Consumer-Meta"
**Objective:** Conversions (Purchase/Book)
**Pixel:** Install Meta Pixel on personal.klaravex.com (required)

### Ad Set 1 — Cold Audience
**Audience:**
- Age: 30-65
- Location: United States
- Interests: NOT tech-savvy (exclude "programming", "software development", "IT")
- Include: homeowners, parents, small business owners, retirees
- Exclude: people who already visited personal.klaravex.com (use pixel)

**Placement:** Facebook Feed, Instagram Feed, Instagram Stories

**Creative (3 variations to A/B test):**

**Ad A — The Rant:**
> Image: Close-up of the spinning wheel of death / hourglass cursor
>
> **Primary text:** You've restarted it three times. You've cleared the cache (whatever that means). You've asked your nephew. He said "have you tried turning it off and on again." It's still slow.
>
> $29. We remote in. We fix it. You watch a show while we work. No time limit.
>
> Your nephew can go back to his video games.
>
> **Headline:** $29. Fixed. Your Nephew Can Relax.
> **CTA:** Book Now

**Ad B — The Receipt:**
> Image: Fake receipt graphic — crossed out prices
>
> **Primary text:**
> ~~Geek Squad: $150 + 5 day wait~~
> ~~Local repair shop: $89 + drive there + no parking~~
> ~~Your "tech-savvy" coworker: free but now your desktop icons are gone~~
>
> Klaravex: $29. Remote. Fixed while you watch. No time limit.
>
> **Headline:** The Last Computer Repair Receipt You'll Need.
> **CTA:** Book Now

**Ad C — The Honesty:**
> Image: Person on couch, laptop on coffee table, remote session visible on screen
>
> **Primary text:** Honest question: how many hours have you spent trying to fix your own computer this year?
>
> Now multiply that by what your time is worth.
>
> We charge $29 and it takes us about 20 minutes because we do this 50 times a day.
>
> **Headline:** 20 Minutes. $29. Done.
> **CTA:** Book Now

**Ad D — The Printer:**
> Image: Printer with "PC LOAD LETTER" or paper jam
>
> **Primary text:** Your printer is not broken. It just hates you specifically.
>
> $29 and we'll convince it to cooperate. Remotely. While you go get coffee.
>
> We've fixed 11,000 printers. Yours isn't special. (But you are.)
>
> **Headline:** $29 Printer Therapy Session.
> **CTA:** Book Now

### Ad Set 2 — Retargeting
**Audience:** personal.klaravex.com visitors (last 14 days) who didn't convert
**Budget:** 30% of Meta spend ($45/mo)

**Creative A:**
> **Primary text:** So you visited our site, looked at the $29 price, and thought "that can't be real."
>
> It's real. No upsell. No "diagnostic fee." No bait and switch.
>
> $29. We fix your computer. That's it. That's the whole business model.
>
> **Headline:** Yes, It's Actually $29.
> **CTA:** Book Now

**Creative B:**
> **Primary text:** Your computer is still slow, isn't it?
>
> We're still $29.
>
> **Headline:** We Can Do This All Day.
> **CTA:** Book Now

---

## Channel 3: LinkedIn — $50/month

### Campaign: "KLX-Consumer-LinkedIn"
**Objective:** Website conversions
**Format:** Single image + text

**Audience:**
- Job titles: Office Manager, Executive Assistant, Practice Manager, Office Administrator
- Company size: 1-50 employees
- Location: United States
- Exclude: IT professionals, software engineers

**Creative A:**
> **Text:** IT said they'd "get to it by Friday." It's Wednesday. Your laptop is still doing that thing.
>
> $29. We fix it during your lunch break. Your IT team doesn't need to know.
>
> **Headline:** Fixed Before IT Opens Your Ticket.
> **CTA:** Book Now

**Creative B:**
> **Text:** You're an office manager. Your job title doesn't say "IT support" but your Tuesday afternoon does.
>
> $29. We take the printer, the VPN, and the "my email isn't working" off your plate. Remotely. Right now.
>
> **Headline:** $29. IT Is No Longer Your Problem.
> **CTA:** Book Now

**URL:** `https://personal.klaravex.com/?utm_source=linkedin&utm_medium=cpc&utm_campaign=consumer-linkedin`

---

## Conversion Tracking

| Platform | Event | Trigger |
|----------|-------|---------|
| Google | Purchase | Stripe checkout success redirect |
| Meta | Purchase | Meta Pixel fires on /thank-you or Stripe success |
| LinkedIn | Conversion | LinkedIn Insight Tag on success page |

**Required setup before launch:**
1. Google Ads conversion tracking tag on personal.klaravex.com
2. Meta Pixel installed on personal.klaravex.com
3. LinkedIn Insight Tag installed on personal.klaravex.com
4. Stripe success redirect → personal.klaravex.com/thank-you (with conversion tags)

---

## Success Metrics (30-day targets)

| Metric | Target |
|--------|--------|
| Cost per session booked | < $15 |
| Sessions booked / month | > 30 |
| Revenue / month | > $870 ($29 × 30) |
| ROAS | > 1.7x |
| Click-through rate | > 3% (Search), > 1% (Meta) |

**Scale trigger:** If CPA < $10 for 7 consecutive days, double daily budget.
**Kill trigger:** If CPA > $25 after 14 days, pause and restructure.

---

## Phase 2 (after 30 days of positive ROAS)

1. Add subscription upsell: "$29/mo unlimited support" on thank-you page
2. Launch YouTube pre-roll ads targeting "how to fix slow computer" viewers
3. Test TikTok ads (15-sec "we fixed this in 29 seconds for $29")
4. Lookalike audiences on Meta from paying customers
5. Google Performance Max campaign using conversion data
