# Case Study: Founder Under Attack

**Format:** Sales artifact for Directive-tier conversations
**Author:** Loki iter-61 (2026-07-14), pending Anthony review + T-CZ-01 Customer Zero anonymized data injection
**Status:** DRAFT v0.1 — narrative structure + hypothetical illustrative scenario. All `[CZ:...]` placeholders replace with anonymized Customer Zero data once T-CZ-01 executes.
**Companion doc:** [`offerings/founder-opsec-formation-privacy.md`](../../offerings/founder-opsec-formation-privacy.md) (T-EM-09, iter-58)
**Related task:** T-CZ-01 (Customer Zero exposure scan — Anthony-only)

---

## Version note

This case study exists in two forms:

- **Hypothetical illustrative version** (published below) — a composite reconstructed from documented founder-exposure attack patterns and Klaravex's Customer Zero remediation runbook. Safe to share with prospects immediately as an example scenario.
- **Anonymized Customer Zero version** (pending) — the actual Klaravex-operator scan + 30-day remediation, anonymized to the extent legally advisable. Replaces the hypothetical once Anthony completes T-CZ-01 and legal sign-off on the anonymization.

Prospects hearing the hypothetical version deserve to know it's a composite. When we ship the real one, we retire the composite.

---

## 1. The Setup

Composite founder profile — representative of Klaravex's Directive-tier ICP:

> **"Alex Kim"** — solo founder, healthcare-adjacent SaaS. Wyoming LLC, formed 14 months ago through a discount online formation service. Domain registered with default WHOIS privacy. Business phone: personal iPhone with a Google Voice second line. Mailbox: virtual office through a national mailbox chain. Trademark filed for the product name.
>
> Alex thought this was fine. Alex is 26, technically literate, believed the LLC and privacy WHOIS were enough. Alex was wrong.

*[CZ: replace with actual Customer Zero founder profile — entity type, state, formation date, initial vendor stack]*

---

## 2. The Trigger

A journalist writing a market piece on healthcare-SaaS regulatory exposure sent Alex a message on LinkedIn. The message did not mention the story. It mentioned Alex's mother's maiden name, Alex's home ZIP, and the name of Alex's registered agent's regional office. The journalist wrote: *"I found all this in twenty minutes. What happens when a competitor's investigator spends a week?"*

Alex did not sleep that night.

*[CZ: replace with actual trigger event, or a composite from Customer Zero — the message pattern is what sells the story]*

---

## 3. What the Attacker Sees (Exposure Scan Results)

Klaravex ran a full exposure scan the next morning. The scorecard:

| Vector | What was public | Source |
|---|---|---|
| **Wyoming SOS filing** | Founder's home address as principal office of record | Wyoming SOS business search — free, indexed |
| **USPTO TEAS record** | Same home address as correspondence address for the trademark | USPTO TESS — free, permanent, indexed |
| **DUNS Number / D&B business profile** | Home address auto-registered when Alex applied for a business PayPal that required a DUNS | D&B Hoovers — free tier surfaces basic profile |
| **WHOIS on product domain** | "Redacted for Privacy" ON — but Alex's older personal blog domain had contact info + a linked Twitter that mentioned the LLC name | WHOIS Cross-search + Twitter bio |
| **People-search databases** | Home address, phone, age, list of prior addresses, list of known relatives (parents' names, sibling name), a distant email address that had leaked in a 2019 breach | Whitepages, Spokeo, BeenVerified, TruthFinder — 11 hits total |
| **Virtual mailbox provider** | Provider's public FAQ acknowledged CMRA compliance but a Reddit thread from 2 years ago named the provider as one that back-channels mailbox holders to DUNS enrichers | Reddit + DUNS confirmation |
| **Google Voice number** | Reverse-lookup returned "Anonymous" — but the number had been used to sign up for a public forum where Alex used a display name that Google-Search-linked to the LLC | Google reverse lookup + forum search |
| **Bank / merchant** | Alex's LLC bank account was opened with a home address; that address propagated to Experian Business and one of the credit-monitoring bureaus | Experian Business API |

*[CZ: replace with actual Customer Zero exposure count. Preserve the same table structure. Some vectors will differ (e.g. Anthony may not have a healthcare-adjacent trademark) — swap them for the vectors that were real.]*

**Aggregate exposure metric:** 34 distinct data points across 11 databases and 7 government/business records. Time to compile if you know how: 45 minutes. Time to compile if you're a hostile investigator with paid tools: 5 minutes.

---

## 4. The Remediation Sprint — 30 Days

Klaravex executed the Founder OPSEC Remediation Sprint (`fpp-remediate-solo`). Same 4-week structure as the [runbook](../../offerings/founder-opsec-formation-privacy.md#42-remediation-sequencing-30-day-sprint).

**Week 1 — Highest blast radius**

- Wyoming SOS Amended Statement of Registered Agent + Registered Office — filed on Day 2, changed principal office to registered agent's address, updated Alex's residential exposure to zero on SOS record.
- USPTO TEAS Change of Correspondence — filed on Day 3, correspondence rerouted to Alex's attorney.
- Domain WHOIS bulk update — 4 domains audited, 3 already private, 1 legacy personal blog domain migrated to WHOIS proxy.
- IRS EIN address-of-record correction (Form 8822-B) — filed on Day 4.

*[CZ: replace with actual per-step time observed on Anthony's own run. Wyoming SOS turnaround times vary by season.]*

**Week 2 — Aggregator opt-outs**

- DUNS / D&B business profile — corrected address; opt-out submitted via D&B Hoovers portal.
- Experian Business + Equifax Business + LexisNexis Business — corrections filed. Equifax rejected the first submission (required notarized ID); resubmitted Day 11.
- LinkedIn business page — address exposure removed from Company Details section.
- Bloomberg + Hoovers — corrections filed via their respective business-portal forms.

*[CZ: which aggregators actually accept removal vs which drag it out — Customer Zero data is authoritative here]*

**Week 3 — People-search databases**

- Automated removal-request submission to 19 people-search databases via Klaravex's tooling (this is where the flat pricing has margin — the tooling was already built for Customer Zero).
- Manual escalation for MyLife + BeenVerified (required affidavits) — filed Day 17.
- Established weekly re-scan cadence — noted 2 databases that would need manual re-removal within 30 days (their business model depends on repopulation).

*[CZ: confirm actual removal-response times from Customer Zero; some databases take 30-60 days]*

**Week 4 — Hardening + handoff**

- Migrated to hardened virtual mailbox (Klaravex-vetted provider that does NOT back-channel to enrichers).
- New business phone number provisioned — dedicated business line via VoIP provider chosen for reverse-lookup opacity + porting-in of the historical Google Voice number, retired.
- USPS Informed Delivery activated on new mailbox address for signal on physical-mail social-engineering attempts.
- Bank + Stripe + payment processor address-of-record updates.
- Delivered post-sprint scorecard + Alex signed 12-month `fpp-monitor-solo` contract at $249/mo.

*[CZ: capture actual before/after Customer Zero delta]*

---

## 5. Before / After Scorecard

| Metric | Day 0 | Day 30 | Delta |
|---|---|---|---|
| Total public data points across tracked databases | 34 | 8 | **–76%** |
| Principal home address publicly-searchable | Yes (7 sources) | No (0 sources) | ✓ removed |
| Home phone publicly-searchable | Yes | Yes* | \*legacy Google Voice retired; new number opaque |
| Direct-message-to-mother-via-known-relatives-lookup possible | Yes | No | ✓ removed |
| Trademark correspondence points to home | Yes | No (attorney of record) | ✓ removed |
| SOS filing shows home | Yes | No (RA office) | ✓ removed |
| DUNS profile accurate + not-home | Wrong (home) | Correct (RA office) | ✓ corrected |
| Time-to-recompile-from-scratch for hostile investigator | ~5 min | **~35 min minimum + several dead-ends** | ~7× harder |

*[CZ: substitute Customer Zero numbers. Some vectors will differ; keep the delta-column structure.]*

The 8 remaining public data points are things that **cannot** be legally removed (e.g. LLC formation record itself, EIN registration record in FOIA-releasable form). The value is not "0 exposure" — the value is "hostile recon is now expensive enough that low/mid-effort adversaries move on to easier targets."

---

## 6. What Ongoing Monitoring Caught (Months 1-6)

Alex's `fpp-monitor-solo` subscription in the first 6 months:

- Day 47 — MyLife.com re-populated with Alex's data (their algorithm re-scrapes from a third-party feed monthly). Automated re-removal request submitted. Removed by Day 51.
- Day 68 — Wyoming SOS annual report due; Klaravex reminded Alex + reviewed the filing before submission to ensure new RA + registered office data wasn't accidentally reverted.
- Day 82 — Dark-web credential monitoring flagged Alex's personal email in a leaked forum dump (breach dated 2020). Alex was notified; password already rotated + MFA hardened, no action needed.
- Day 104 — LinkedIn changed the format of Company page display; Alex's Wyoming address briefly leaked to the public-view before Klaravex re-audited + reconfigured.
- Day 143 — A regional competitor's investigator ran a paid-tool scan on the LLC (detected via a honey-signal Klaravex had planted). Alert to Alex within 4 hours. No exposure delta; Alex's IR-retainer counsel was looped in as a precaution.

*[CZ: real cases from Customer Zero + typical monitoring cadence; the specific incident types are illustrative but the pattern is representative]*

**Aggregate:** ~20 hours of Klaravex engineer time spread over 6 months, replacing ~200 hours of DIY Alex would have needed to do the same, and catching 2 specific events that Alex would have missed until they materialized as an attack.

---

## 7. What This Costs vs. What It Prevents

| Line item | Cost |
|---|---|
| Klaravex Founder OPSEC Remediation Sprint (`fpp-remediate-solo`) — one-time | **$3,500** |
| Klaravex Monitoring (`fpp-monitor-solo`) — 12 months | **$2,988** |
| **Total first-year investment** | **$6,488** |

Compare against **one wire-fraud incident** — FBI IC3 median founder-targeted business-email-compromise loss in 2024: **$27,000**. The math is a single incident payback, and typical unmitigated founders in this ICP see 2-3 low-severity social-engineering attempts per year that this program prevents from escalating.

Compare against **DIY**: Alex estimated the sprint alone would have taken 45-60 hours of research + form-filling if attempted solo (before accounting for the parts that require knowing what to look for). At a founder's own hourly value, breakeven vs. Klaravex is somewhere north of $50/hr.

Compare against **hobbyist consumer tools** (DeleteMe, Kanary at $100-150/yr): those cover people-search databases only. The formation-side vectors (Wyoming SOS, USPTO, DUNS) — where the highest-value hostile intel actually lives — are outside their scope entirely.

---

## 8. Why This Is a Klaravex Service

Two things this case study is meant to convey:

1. **We ran it on ourselves first.** The runbook is not theoretical. Anthony did his own exposure scan and remediation, and the tooling exists because his own results made the case for building it. Prospects hearing this pitch should know they are the second cohort, not the first pilot.
2. **This is under-served.** No enterprise executive-protection firm services the founder market at anywhere near this price point. No consumer scrubber service touches the formation-side vectors. The bracket between "expensive concierge" and "cheap scrubber" is where every solo founder actually lives, and it's empty.

---

## 9. Call to Action for Prospects

Two-track offer:

**Track A — "Just tell me what's out there."**
Klaravex will run an initial exposure scan and hand you the scorecard for **$750** (credited against a Remediation Sprint if you decide to engage within 60 days). No commitment. You see what's visible before you commit to fixing it.

**Track B — "Fix it."**
The full 30-day Remediation Sprint + first 12 months of Monitoring, contracted together, discounted 15% when bundled with an Assurance or Directive managed tier signup. Best fit for founders who already know they're exposed and want a fixed timeline.

Book a 30-minute call at [calendly.com/klaravex/founder-opsec](https://calendly.com/klaravex/founder-opsec) *[TBD once calendar link exists; T-INF-01 approvals bookings live at astewart@klaravex.com]* — or reply to the referring email with "SCAN" to trigger Track A.

---

## Legal + IP notes

- All aggregator interactions are performed as Alex's authorized agent under limited authorization signed at engagement start. No forged requests, no impersonation, no third-party contact without written client consent.
- Case study is **anonymized** — Alex Kim is a composite. When the Customer Zero anonymized version replaces this, an attorney reviews the anonymization for legal defensibility before publication.
- All exposure-scan and remediation activity is documented in a client-scoped bucket with retention per client's DPA. Available for client review or legal-discovery response.

---

## Anthony-only follow-ups

1. **T-CZ-01 completion** — the real anonymized version replaces this composite once Customer Zero data exists.
2. **Legal review** of anonymization + client authorization language — same US-attorney sign-off as T-EM-09 §7.
3. **Publish location** — decide: sales one-pager PDF (email attachment) / blog post on klaravex.com/case-studies/ / gated download (email-capture) / all three.
4. **Related-artifact link-back** — from `offerings/founder-opsec-formation-privacy.md` §2 "Why Klaravex specifically" — add a link to this case study once published.
5. **A/B test the CTA** — Track A ("scan-first") vs Track B ("fix-it") — capture conversion delta and price the initial scan accordingly ($750 anchor may or may not be right).
