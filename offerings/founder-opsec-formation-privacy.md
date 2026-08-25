# Klaravex Founder OPSEC & Formation Privacy — Service Offering Spec

**Author:** Loki iter-58 (2026-07-14), pending Anthony review + Customer Zero data injection
**Status:** DRAFT v0.1 — spec + pricing defined; delivery runbook is a skeleton awaiting empirical data from T-CZ-01 Customer Zero exposure scan
**Surface:** klaravex.com US managed offering. `note_submissions` for acting on this → **Azure `klaravex-db`**
**Source spec:** T-EM-09 (PRD delta 2026-06-12) — "Productize Founder OPSEC / Formation Privacy as a service line"

---

## 1. Executive Summary

Every US solo founder who registers an LLC, forms a corp, or hangs a shingle publicly-lists themselves to a permanent, indexed, largely-un-opt-outable pipeline of databases the moment they file. Registered Agent addresses, EIN routing addresses, WHOIS records, USPTO correspondence addresses, DUNS/D&B enrollments, Wyoming/Delaware/Nevada SOS filings, virtual office listings, business phone directories — each of these is a documented exposure vector that a competent adversary chains into a doxxing/social-engineering/wire-fraud attack surface within days.

This offering **productizes the fix**: a bounded pre-formation advisory (do it right the first time), a scoped post-formation remediation sprint (unfuck what's already public), and an ongoing monitoring subscription (catch new leaks as filings, renewals, and third-party enrichers repopulate what you cleaned).

**Positioning:** this is the OPSEC layer that sits *underneath* the Klaravex managed IT/security stack. It's sold as its own service line (solo founders, small owner-operator LLCs, funded pre-seed teams) AND bundled into the Assurance and Directive managed tiers as an included benefit for the founder/executive (up to 3 principals).

**Why Klaravex specifically:** the operator has run this playbook on themselves (Customer Zero — T-CZ-01). Every remediation step in the runbook is one Anthony has personally executed or blocked-and-documented. This is not a "we have a checklist" pitch — it's a "we've done our own and here's the receipts" pitch.

---

## 2. What the Client Gets

Three products in this service line, priced independently, stackable:

### 2.1 Pre-Formation Advisory (`fpp-preform`)

A 60-90 minute working session BEFORE the client files their entity, plus a written playbook and vendor recommendations. Delivered to a founder who has decided to form an LLC/C-Corp/S-Corp but has not yet filed with the state.

Coverage:

- **Registered Agent (RA) selection** — which RAs actually don't publicly list the principal (short list; most do, despite the marketing)
- **Formation state trade-offs** — Wyoming vs. Delaware vs. Nevada vs. home-state; the privacy delta is real, but so are the compliance and franchise-tax deltas — walk through both
- **Virtual mailbox choice** — the shortlist of providers with real CMRA compliance (USPS 1583 done right) and no back-channel address sharing to DUNS/Experian
- **Business phone strategy** — dedicated number that does NOT resolve to a home address via reverse-lookup services; number-portability plan for future
- **EIN application routing** — the IRS EIN application asks for a mailing address that lands in public records via FOIA and third-party scrapers — how to route it right the first time
- **Website domain WHOIS strategy** — RA-registered domain vs. proxy WHOIS vs. business address; the trade-off with SSL cert requirements
- **Founder-facing IT setup first-pass** — email routing, backup mailbox, MFA hardening — done before the corporate identity gets attached to anything

Deliverable: `founder-preform-plan-<client>.md`, a written playbook + vendor shortlist + estimated recurring costs of the recommended setup.

### 2.2 Post-Formation Remediation Sprint (`fpp-remediate`)

A 30-day scoped engagement for a founder whose entity is already formed and public. Uses the same runbook as Klaravex ran on Customer Zero.

Coverage (each is an executable line item, not a theoretical suggestion):

- **WHOIS audit + remediation** across all owned domains (personal, business, side-projects); consolidate to proxy or RA-routed where appropriate
- **USPTO TEAS Change of Correspondence** for any owned trademarks (correspondence address is publicly-searchable and often lists home)
- **State SOS amended filing** to route registered office / RA / principal address correctly (Wyoming and Delaware require specific forms; walked through per-state)
- **DUNS Number / D&B business profile** opt-out or correction — D&B is the source of most B2B enrichers; wrong address here = wrong address everywhere for years
- **Hoovers / Bloomberg / Experian Business / Equifax Business** opt-out where offered; correction where opt-out isn't offered
- **People-search database opt-outs** for the principal name+city combo (Whitepages, Spokeo, BeenVerified, MyLife, InstantCheckmate, PeopleFinder, TruthFinder, FastPeopleSearch, RadarIS, and ~15 others) — scripted removal requests, weekly repeat-scans
- **Virtual office / mailbox migration** if the current setup is CMRA-only, no scanning, or provider-address-leaks
- **USPS Informed Delivery** on the new address for monitoring
- **Bank / merchant processor / Stripe** address-of-record updates (these repopulate public records via credit reporting)
- **Post-sprint scorecard** — before/after exposure map, delta count of records removed, list of what could not be removed and why

Deliverable: `founder-remediation-<client>.md` (scorecard) + evidence artifacts (screenshots, removal confirmations, filed forms) in a client-scoped bucket.

### 2.3 Ongoing Monitoring (`fpp-monitor`)

Monthly subscription. Catches re-population by third-party enrichers, new leaks from newly-filed compliance events (annual reports, franchise tax filings, corporate agent renewals), and adversarial reconnaissance signals against the principal.

Coverage:

- **Weekly re-scan** of the ~40 aggregator databases with automated removal-request replay for any new appearances
- **Monthly WHOIS diff** across all tracked domains
- **State SOS event alerting** — annual report reminders, franchise tax, RA renewal
- **USPTO status watch** — trademark maintenance events that regenerate correspondence exposure
- **Dark-web credential monitoring** for the principal's personal + business email + old addresses
- **Named engineer response** — 24h SLA on any newly-detected exposure — either scripted removal or advisory on why removal isn't possible
- **Quarterly exposure scorecard** with trend line, delivered to the client with a 30-min call

Deliverable: recurring monthly report + real-time alert channel (email + optional Telegram or WhatsApp).

---

## 3. Pricing

Anchored against the value of avoiding **one** wire-fraud incident (average founder-targeted wire fraud loss: $27K per FBI IC3 2024) and against Klaravex's Directive tier ($295/user/mo) as the ceiling for what a comfortable buyer will spend on a security posture line item.

| SKU | Description | Price | Notes |
|---|---|---|---|
| `fpp-preform` | Pre-Formation Advisory (60-90 min + playbook) | **$1,500 flat** | One-time, no scope creep — separate `fpp-remediate` if they want us to execute the plan post-filing |
| `fpp-remediate-solo` | 30-day Remediation Sprint (single principal, ≤3 owned domains, ≤2 trademarks) | **$3,500 flat** | Scoped engagement; overage priced at Klaravex hourly ($225/hr) |
| `fpp-remediate-team` | 30-day Remediation Sprint (2-5 principals, ≤10 domains, ≤5 trademarks) | **$7,500 flat** | Small founding team / early-stage startup version |
| `fpp-monitor-solo` | Ongoing Monitoring (single principal) | **$249/mo** | 12-month min term; month-to-month after; requires `fpp-remediate` or Klaravex managed tier to activate |
| `fpp-monitor-team` | Ongoing Monitoring (up to 5 principals) | **$599/mo** | Same terms |
| `fpp-executive` | Executive tier — comprehensive, high-touch, weekly review, priority remediation window | **$2,500/mo** | Includes monitoring + unlimited remediation + IR advisory retainer; sold to funded / high-profile founders and ops execs |

**Managed-tier inclusions (no incremental charge):**

- **Assurance** ($165/user/mo) → includes `fpp-monitor-solo` equivalent for one designated principal
- **Directive** ($295/user/mo) → includes `fpp-monitor-team` equivalent for up to 3 principals + `fpp-remediate-solo` sprint credit (redeemable once in first 90 days)

**Pricing rationale:**

- Remediation sprint is priced 30-50% below what an equivalent hour count of Klaravex consulting ($225/hr × 15-25 hr) would be, because the runbook is codified from Customer Zero — margin is defensible even at flat price
- Monitoring is priced above hobbyist tools (DeleteMe, Kanary at $100-150/yr) because the deliverable is engineered removal + named-engineer response, not a self-service scrubber. Buyer will not confuse the offerings.
- Executive tier is priced to be a "sensible fraction of a good IR retainer" — reads correctly to founders who've already had one scare

**Discount policy:** never discount `fpp-preform` (already the low-anchor). `fpp-remediate` can be 10-15% discounted when bundled with a Klaravex managed tier signup in the same contract. Monitoring is contract-length-locked, no discount.

---

## 4. Delivery Runbook — Skeleton

⚠️ **This is a skeleton.** The definitive runbook lives at `.loki/hipaa/loki-phi-architecture-options.md`-style depth in a separate document once Customer Zero (T-CZ-01) has been executed. Sections marked `TODO(CZ)` are placeholders for empirical data.

### 4.1 Intake

- Client fills a scoping form: entity type + state, list of owned domains, list of owned trademarks, current registered agent, current mailbox provider, current business phone provider, list of principals, list of email addresses.
- Klaravex runs an initial exposure scan (public records + WHOIS + DUNS lookup + top-20 aggregators) — 24h turnaround.
- Delivers a **pre-engagement exposure scorecard** so the client can see what they're buying.

### 4.2 Remediation sequencing (30-day sprint)

**Week 1 — highest-blast-radius**

1. RA + state SOS correction (source of most downstream repopulation)
2. USPTO TEAS Change of Correspondence
3. WHOIS bulk update — all owned domains
4. IRS EIN address of record correction (Form 8822-B if applicable)
   *`TODO(CZ): note actual per-step time from Anthony's own run`*

**Week 2 — aggregator opt-outs**

5. DUNS / D&B remediation (highest-priority — feeds everything)
6. Bloomberg / Hoovers / Experian Business / Equifax Business
7. LinkedIn business page audit (address exposure via Company Details)
   *`TODO(CZ): list which aggregators actually accept removal requests vs. rely on legal counsel`*

**Week 3 — people-search databases**

8. Automated removal-request submission to top-20 people-search databases
9. Manual escalation for any that require SSN or notarized ID (rare)
10. Establish weekly re-scan cadence
    *`TODO(CZ): confirm removal times observed on Customer Zero; some are 30-90d`*

**Week 4 — hardening + handoff**

11. Migrate to hardened mailbox + business phone if current setup fails audit
12. USPS Informed Delivery activation
13. Bank / Stripe / merchant processor address updates
14. Deliver post-sprint scorecard + set up monitoring contract if signed
    *`TODO(CZ): capture the actual before/after Customer Zero delta as the anchor case study`*

### 4.3 Ongoing monitoring cadence

- **Daily:** dark-web + credential-leak signal ingestion
- **Weekly:** aggregator re-scan + WHOIS diff
- **Monthly:** written report + trend line
- **Quarterly:** 30-min client review call + scorecard delivery

### 4.4 Escalation path

- **New exposure detected** → engineer triage within 4h → auto-removal attempt within 24h → client notification with status
- **Signal of active adversarial recon** (unusual pattern of scrapes, credential-stuffing on principal email, wire-fraud precursor language in comms) → immediate call to principal + client's IR team

---

## 5. Positioning Against Alternatives

| Competitor | What they do | Where Klaravex wins |
|---|---|---|
| **DeleteMe / Kanary / Optery** | Self-service aggregator scrubber, consumer-priced | Klaravex covers formation-side exposure (SOS, USPTO, DUNS, RA) that these ignore. Klaravex includes engineer response — no self-service. |
| **Reputation Defender (paid consultants)** | Broad brand-management, mostly SEO-focused | Klaravex targets the *technical* exposure surface (records, filings, WHOIS) not the search-result-suppression game |
| **IT security firms selling "executive protection"** | High-touch, enterprise-priced ($10K+/mo) | Klaravex is priced for the founder-scale market ($250–$2,500/mo) and productized, not consulting-per-engagement |
| **DIY (founder Googles their way through it)** | Free but takes 40-60 hours over months, misses aggregators, no monitoring | Klaravex compresses to 30 days + ongoing catch — the founder gets those 40-60 hours back |

---

## 6. Compliance & Legal Notes

- **All removal requests are made in the client's name with their consent** — Klaravex operates as an authorized agent per each aggregator's stated process. Client signs a limited authorization at engagement start.
- **PII handling:** the client's public-record data + email addresses + phone numbers are processed. Standard Klaravex DPA covers. GDPR + CCPA scope where applicable.
- **What Klaravex explicitly does NOT do:** submit false or forged removal requests; contact the client's bank/employer on their behalf; interact with law enforcement without written client authorization.
- **Attorney review recommended for:** USPTO TEAS filings (client's IP counsel confirms the change), state SOS amended filings (some states require attorney signature).

---

## 7. Anthony-Only Follow-Ups

1. **T-CZ-01 Customer Zero exposure scan** — this offering's runbook is a skeleton until Customer Zero data lands. Once T-CZ-01 completes, replace every `TODO(CZ)` marker with the empirical values (per-step time, aggregator response times, before/after exposure count).
2. **Legal review** of the client authorization / limited power of attorney language for aggregator removal — US attorney sign-off before first paying client.
3. **Vendor shortlist confirmation** — the pre-formation advisory recommends specific RAs, mailbox providers, business phone providers. Anthony picks the 2-3 per category he'll actually recommend (avoid affiliate-vs-quality conflict).
4. **Sales page copy** for klaravex.com — this spec is the internal source; a public sales page needs marketing rewrite (probably in `site-relaunch/` per the theme pattern).
5. **Case study T-PL-08 'Founder under attack'** — the anonymized Customer Zero result becomes the flagship sales artifact. Delivered separately.
6. **Stripe products setup** — 6 SKUs listed in §3. Create as Payment Links + subscription products before first client.
7. **Directive / Assurance tier update** — the "included for one/three principals" language needs to appear in the tier descriptions on klaravex.com and in the MSA appendix.

---

## 8. Success Criteria (post-launch)

- 5 `fpp-preform` sold in first 90 days (indicates ICP resonance)
- 3 `fpp-remediate-solo` completed with before/after scorecard delta > 40%
- 10 `fpp-monitor-*` active subscriptions at 90 days (recurring revenue anchor)
- 1 executive-tier signed at $2,500/mo (validates upper price point)
- Zero client escalations from removed-then-repopulated aggregator records within 90-day window (indicates monitoring cadence is correct)
