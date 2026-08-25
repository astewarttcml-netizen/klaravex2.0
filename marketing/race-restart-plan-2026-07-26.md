# Marketing Race Restart Plan — 2026-07-26

## Why it stalled
- 97% rejection rate (359/369 drafts rejected for voice policy violations)
- Marketing autopilot killed after email flood
- Both teams still on soft_launch ($100 budget)
- /race page has no conversion mechanism (email capture, CTA)

## What changed since then
- Voice policy enforcement fixed (TEAM_SYSTEM_HEADER rewritten)
- Marketing autopilot rebuilt with dedup + cooldown + weekly plan system
- Scam recovery FREE service launched (the marketing stunt)
- All 4 landing pages live (healthcare, legal, financial, vCISO)
- Google Ads approved + 7 ad groups ready
- Meta Ads full pipeline fixed
- Twitter/X + Reddit Playwright selectors fixed
- All consumer Stripe links wired

---

## The Restart: Week 1 Plan

### Shared assets (both teams use)
- Scam recovery free service (the hook — differentiator no competitor has)
- 4 vertical landing pages with Calendly CTAs
- Consumer Stripe checkout (all services live)
- Chat widget (live on both sites)
- Phone system (24/7, all specialists)

### Team Alpha — "Fast Spend" (paid acquisition)

**Philosophy:** Speed, volume, paid channels. Test fast, kill losers, scale winners.

**Week 1 plan (submit via /api/v1/internal/marketing/submit-weekly-plan):**

| Day | Channel | Action | Budget |
|-----|---------|--------|--------|
| Mon | Google Ads | Launch Healthcare/HIPAA ad group (PAUSED→ACTIVE) | $30/day |
| Mon | LinkedIn | Sponsored post: scam recovery free service | $20 |
| Tue | Google Ads | Launch Legal ad group | included |
| Tue | Meta | Consumer awareness: scam recovery | $15/day |
| Wed | Google Ads | Launch Financial ad group | included |
| Wed | LinkedIn | Sponsored post: vCISO for SMBs | $20 |
| Thu | Google Ads | Launch vCISO ad group | included |
| Thu | Meta | Retarget landing page visitors | $10/day |
| Fri | Google Ads | Launch Scam Recovery (free) ad group | $10/day |
| Sat | Review | Pause underperformers, double winners | — |
| Sun | — | Let ads run | — |

**Week 1 budget:** ~$350 of $1,000

### Team Beta — "Patient ROI" (organic + content)

**Philosophy:** Content-first, build authority, earn trust, convert through value.

**Week 1 plan:**

| Day | Channel | Action | Budget |
|-----|---------|--------|--------|
| Mon | LinkedIn | Organic thought leadership: "We made scam recovery free. Here's why." | $0 |
| Mon | X/Twitter | Thread: scam recovery story (6 tweets) | $0 |
| Tue | Reddit | r/msp post: "We're running an experiment — two AI marketing teams..." | $0 |
| Tue | LinkedIn | Poll: "Should MSPs offer free scam recovery?" | $0 |
| Wed | HN | Show HN: portal.klaravex.com/race | $0 |
| Wed | Blog | "Why we publish our AI agents' CAC" (SEO play) | $0 |
| Thu | LinkedIn | Case study angle: governed AI in production | $0 |
| Thu | Email | Race digest #1 to subscribers | $0 |
| Fri | X/Twitter | "Week 1 standings" with scoreboard screenshot | $0 |
| Sat | Reddit | r/sysadmin: free scam recovery for anyone | $0 |
| Sun | — | Rest | — |

**Week 1 budget:** $0 (all organic)

---

## /race Page Fixes (do before restart)

1. **Email capture** — "Get the weekly race digest" with name + email form
2. **Budget display** — show actual budget ($100 soft-launch → $1,000 full)  
3. **Governance wording** — "autonomous within governance" not "full autonomy"
4. **Scoreboard** — add leading indicators (booked calls, signups) not just revenue
5. **Directive CTA** — "This governance runs our clients' IT → book a briefing"
6. **Rules link** — public rulebook (spend rules, approval gates, AI labeling)

## Restart Sequence

1. Fix /race page (items above)
2. Flip both teams to `live` status
3. Set budgets: Alpha $1,000, Beta $1,000
4. Submit Week 1 plans via the new weekly plan API
5. Post teaser: "Something's been running at portal.klaravex.com/race"
6. T+3: Full launch post + X thread
7. Daily: draw-daily cron executes approved plan items
8. Weekly: teams submit next week's plan, Anthony reviews batch

## Success Metrics (Week 1)

| Metric | Alpha target | Beta target |
|--------|-------------|-------------|
| /race visitors | 200 (from ads) | 300 (from organic) |
| Email signups | 20 | 30 |
| Calendly bookings | 2 | 1 |
| Content published | 5 ads live | 8 organic posts |
| Spend | $350 | $0 |
