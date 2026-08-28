# Charter: Social Growth (Engagement + Followers)

Owner: **Nadia** (Head of Growth). Execution: Socials agent + Zernio dispatch.
Companion to `charters/socials.md` (draft/media rules). This file owns **where
attention goes**, **what we measure**, and **how we route publish**.

## Timezone (binding)

**Dual-coast USA clocks:**

| Coast | IANA | Role |
|---|---|---|
| **Eastern** | `America/New_York` (`GROWTH_TIMEZONE`) | Ops timers + **B2B** publish default |
| **Western** | `America/Los_Angeles` (`GROWTH_TIMEZONE_WEST`) | **B2C** publish default (Pacific) |

Default organic slots (when scheduling, not `--publish-now`):
- **B2B** (klaravex.com / page LI / business shorts) → **10:00 AM Eastern**
- **B2C** (personal.klaravex.com / Zernio / consumer shorts) → **10:00 AM Pacific**

Do not schedule audience posts in Europe/Berlin wall time.
## North-star metrics (Nadia digest KPIs)

Track weekly (Mon digest); daily digests only flag misses.

| KPI | Target (30-day) | Source | Notes |
|---|---|---|---|
| LinkedIn personal posts shipped | 4–5 / week | Zernio BRIDGED | Often carries **B2C** copy → personal.klaravex.com |
| LinkedIn page posts shipped | 2–3 / week (weekdays) | Zernio `linkedin` Klaravex | **B2B** → klaravex.com |
| TikTok clips shipped | 4–7 / week | Zernio `@klararavex` | Unique 9:16 each; no cross-reuse |
| YouTube Shorts shipped | 3–5 / week | Zernio `@klaravex` | Unique edit; Soft CTA |
| Draft → APPROVED → BRIDGED rate | ≥ 70% of gated socials | Outbox + digests | Escalation if APPROVED unbridged |
| Soft engagement proxy | Comments + profile clicks | Manual / platform UI until wired | Prefer over raw follower count |
| Site intent | klaravex.com + personal.klaravex.com visits w/ UTM | Analytics when available | `?utm_source=linkedin\|tiktok\|youtube&utm_campaign=<theme-slug>` |

**Do not optimize for:** follower vanity on LinkedIn page, equal volume on every
network, boosting losers with ads.

## Platform roles (attention budget)

| Platform | Role | Primary route | Cadence |
|---|---|---|---|
| LinkedIn **personal** (Zernio) | Channel for **B2C** track (personal.klaravex.com) | **Zernio** `linkedin` (personal profile) | 4–5×/week |
| LinkedIn **page** (Klaravex) | Channel for **B2B** track (klaravex.com) | **Zernio** `linkedin` | 2–3×/week, Mon–Fri |
| TikTok (`@klararavex`) | Discovery / reach | **Zernio** | 4–7×/week |
| YouTube Shorts (`@klaravex`) | Search + durable short | **Zernio** | 3–5×/week |
| Instagram / X / Facebook | Amplifier only | Zernio when capacity | After LI+TT stable |
| Reddit | Authority answers (forums lane) | Manual / Zernio `KlaravexAi` | 3–5 useful replies/week — see Forums section |
| Pinterest | Parking lot | Zernio account connected | Not in 30-day focus |

**Ads** stay in the ads stream (proposals only) — never confuse with organic
Zernio posts. Boost only after a post earns comments/saves.

## Routing rules (binding)

1. **B2B track** (klaravex.com) LinkedIn → Zernio Klaravex Page.
2. **B2C track** (personal.klaravex.com) LinkedIn → Zernio personal profile
   (corporate "we" voice in draft body; Zernio is the *channel*).
3. **TikTok + YouTube Shorts** → Zernio; unique media files per platform.
   B2B shorts → klaravex.com; B2C shorts → personal.klaravex.com.
4. **Never** reuse one video/still across TikTok and YouTube (or across tracks).
5. Drafts remain gate-APPROVED before any dispatch; publish is Anthony/Nadia
   approval (Zernio drafts first unless explicitly told to publish).

## 30-day theme calendar (one theme per ISO week)

Rotate so the feed teaches one problem family, not random topics.

| Week offset (ISO week % 4) | Theme slug | Business angle | Consumer angle |
|---|---|---|---|
| 0 | `hipaa-habits` | Portal access, backup retention, access reviews | Why clinics/small practices skip boring controls |
| 1 | `mfa-edge-base` | Layered controls before audit theater | MFA + hardened edge (firewall first; UniFi only if LAN topic) |
| 2 | `access-reviews` | Who has PHI/systems access this month | Shared logins / orphaned accounts at home office |
| 3 | `incident-boring-work` | Habits that prevent tomorrow's incident | "Wi‑Fi is up, MFA is maybe" |

Hooks must open on tension or a concrete miss in the first line / 2 seconds —
never "We're excited to share."

## Daily engagement block (Nadia / operator)

15–20 minutes, LinkedIn-first:

1. Comment on 5–8 clinic IT / MSP / readiness posts with one useful sentence.
2. Reply to every comment on Klaravex posts same day.
3. Soft CTA only once per post; prefer a question prompt for comments.

## Kill criteria (week 3–4 of each month)

Double down on the 2 formats with comments/saves; pause the rest until the
next theme week. Record the kill list in that week's Nadia digest Suggested
actions.

## Forums (authority channel — not follower farming)

Forums convert **trust → DMs/site**, not vanity followers. Treat them as a
third lane next to B2B page LinkedIn and B2C (personal LI + TikTok) — slower,
higher intent.

### Where Klaravex should show up

| Venue | Account | Fit | Notes |
|---|---|---|---|
| Reddit `r/sysadmin`, `r/msp`, `r/healthcareIT`, `r/smallbusiness` | Zernio `KlaravexAi` (or manual) | High | Answer threads; rare soft CTA |
| Reddit verticals (HIPAA / medical office IT when on-topic) | same | Medium | Never pitch in first reply |
| Spiceworks / similar MSP boards | Manual / Anthony | Medium | Prep answers in outbox; human posts |
| Vendor community forums (UniFi, Palo/Fortinet/Cisco, M365 admin) | Manual | Medium | Product-helpful, brand light |
| Skool / owned community | klaravex-os tool path | Later | After organic LI+TT+Reddit rhythm exists |
| Pinterest | Connected (`astewart0988`) | Low (30-day) | Not a forum; ignore for now |

### Rules (binding)

1. **Answer first, brand second.** Lead with the fix; Klaravex + link only if
   the thread asks for a vendor/process or after a useful reply lands.
2. **No blast posts.** One thoughtful reply beats five promotional threads.
   Zernio Reddit is for rare long-form answers aligned to the week theme —
   not daily socials cross-posts.
3. **Same voice policy** as socials (corporate "we", no "compliance", no
   defense/DIB, readiness/advisory language).
4. **Drafts-only for automation.** Forum replies are prepared by the **forums**
   stream (`charters/forums.md` → `outbox/forums/`). Posting stays
   Anthony/Nadia (Zernio Reddit draft or manual paste) until a forums
   dispatch exists.
5. **Mine research signals.** Growth research already surfaces
   `forum_mentions` — run `python -m growth.forums.harvest` and turn hot
   threads into answer drafts the same week.
### Forums KPIs (Nadia — weekly)

| KPI | Target | Notes |
|---|---|---|
| Useful replies prepared | 3–5 / week | Theme-aligned; outbox drafts |
| Replies actually posted | ≥ 3 / week | Manual or Zernio Reddit |
| Soft CTA rate | ≤ 1 in 3 replies | Prefer no link until asked |
| Inbound from forums | Track DMs / site UTM `utm_source=reddit` | Quality over count |

### Cadence vs socials

- **Mon–Fri:** full stack — B2B (klaravex.com) + B2C (personal.klaravex.com)
  across LI / TikTok / YT, plus forums.
- **Sat–Sun:** **B2C-focused** socials run (timer on 06:30). Prioritize
  personal.klaravex.com — Zernio LI + unique consumer TikTok/YT. Light or skip
  B2B page LI; forums stay Mon/Wed/Fri only.
- **Do not** auto-crosspost TikTok captions to Reddit.

### Research Integration

Growth research already surfaces `forum_mentions` signals — run `python -m growth.forums.harvest` and turn hot threads into answer drafts the same week. These forum mentions represent valuable engagement opportunities that should inform both social media content strategy and direct outreach efforts.

## Backlink Generation

This charter covers the automated generation of backlinks for `klaravex.com` and `personal.klaravex.com`. It is part of a larger content strategy that includes the KB (knowledge base) and outreach.

### Scope

Backlink generation is split into three tiers:
1. **Foundation** - low effort, low-medium authority: Directory citations and profile listings
2. **Earned** - medium effort, medium-high authority: Editorial links from journalist queries and syndication 
3. **Authority** - high effort, high authority: Original research and expert commentary in trade press

### Strategy

This is an automated process that runs on a monthly basis.

### Recent Activity

- 2026-08-21: Created directory submission batch (T-01-T-06) for Google Business Profile, Bing Places, Apple Business Connect, LinkedIn Company Page, Crunchbase, and Dun & Bradstreet.
- 2026-08-21: Updated backlinks playbook with new tracking table and status updates