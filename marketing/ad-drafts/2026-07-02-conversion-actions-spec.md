# T-AC-06 · Primary + Secondary Conversion Actions — Spec

**Date:** 2026-07-02
**Market:** US only (klaravex.com)
**Attribution:** Google Ads · GA4 · LinkedIn Insight Tag · (Meta CAPI when applicable)

---

## 1. Conversion hierarchy

Google Ads Smart Bidding needs **one** primary conversion action per campaign and can factor in secondaries. Set the hierarchy from customer-value order — closest to a paid engagement is primary.

| Tier | Conversion action | Value | Attribution | Notes |
|---|---|---|---|---|
| **PRIMARY** | Readiness Review booked | $250 | GA4 → Google Ads import | The intent signal that converts to pipeline |
| **PRIMARY** | Directive tier quote requested | $500 | Server-side (form submit → webhook) | Highest-intent B2B action |
| Secondary | Readiness Self-Assessment completed (score submitted) | $50 | GA4 event | Mid-funnel qualification |
| Secondary | Readiness Checklist downloaded (LinkedIn form OR site form) | $30 | GA4 event + LinkedIn Insight | Cold audience warmup |
| Secondary | Contact form submitted (general "contact us") | $75 | GA4 event | Lower intent; deduplicated against Readiness Review |
| Secondary | Phone call from ads (>60s) | $150 | Google call tracking | Direct paid-call attribution |
| Secondary | Chat conversation started (>3 message exchanges) | $40 | Klaravex chat webhook → GA4 | Signal-only tier |
| Micro | Newsletter subscribe (blog / cornerstone content) | $5 | GA4 event | Won't factor into bidding; used for RLSA lists |

**Bidding strategy:** Target CPA on Readiness Review + Directive Quote = $150 blended.

---

## 2. Event definitions (GA4)

### 2.1 `readiness_review_booked` (Primary)

**Trigger:** POST to `klaravex.com/readiness-review/submit` returns HTTP 200 with a valid booking ID in the response.
**Server-side event:** yes (fire from klaravex-api, not client-side, to avoid ad-block loss).
**GA4 parameters:**
- `value`: 250
- `currency`: USD
- `vertical`: healthcare | legal | financial | general | consumer
- `channel`: organic | direct | google_ads | linkedin | referral | email
- `source_ad_group`: `{utm_content}` if present
**Google Ads import:** Yes — set as "Primary".
**LinkedIn conversion:** map to LinkedIn `Book_Appointment` action.

### 2.2 `directive_quote_requested` (Primary)

**Trigger:** Contact form submitted with `interest = "Directive tier"` OR the dedicated `klaravex.com/directive/request-pricing` form.
**Server-side event:** yes.
**GA4 parameters:**
- `value`: 500
- `currency`: USD
- `vertical`: (as above)
- `firm_size`: integer (employee count)
- `regulator`: HIPAA | SOC2 | ISO27001 | FTC_Safeguards | multi
**Google Ads import:** Yes — set as "Primary".

### 2.3 `readiness_assessment_completed` (Secondary)

**Trigger:** User submits the interactive readiness self-assessment (final "See my score" click).
**Client-side event OK** (low fraud risk).
**GA4 parameters:**
- `value`: 50
- `currency`: USD
- `score`: integer 0-48
- `red_domains`: comma-separated list of domain names scored Red
**Google Ads import:** Yes — set as "Secondary".

### 2.4 `readiness_checklist_downloaded` (Secondary)

**Trigger:** Either (a) LinkedIn Lead Gen Form submission (webhooked from LinkedIn Marketing API into Klaravex CRM) OR (b) `klaravex.com/thanks/readiness-checklist` page load.
**GA4 parameters:**
- `value`: 30
- `currency`: USD
- `download_source`: linkedin | site
- `email_domain`: from submitted email (helps identify SMB vs personal)
**Google Ads import:** Yes.
**LinkedIn conversion:** map to `Download`.

### 2.5 `contact_form_submitted` (Secondary)

**Trigger:** Any non-Directive-quote form submission on klaravex.com.
**Dedup rule:** If `readiness_review_booked` fires within 30 minutes, do NOT count this event (prevents double-count).
**GA4 parameters:**
- `value`: 75
- `topic`: (user-selected topic from form dropdown)

### 2.6 `phone_call_from_ads` (Secondary)

**Trigger:** Google forwarding number picks up a call >60 seconds.
**Set up:** Google Ads call extension enabled with call reporting. Requires a Google-provided forwarding number (T14.9 blocks call extensions until the main line E.164 is set).
**Value:** $150 per qualified call.

### 2.7 `chat_conversation_started` (Secondary)

**Trigger:** User + Klara (Vapi voice) or Klaravex web chat exchange ≥3 messages.
**Server-side event** from Vapi / chat webhook.
**Value:** $40.

### 2.8 `newsletter_subscribed` (Micro)

**Trigger:** Newsletter form submitted.
**Not imported to Google Ads** — used only for RLSA remarketing lists.

---

## 3. Enhanced Conversions (T-AC-07 sibling)

**Enable enhanced conversions for Google Ads** so hashed first-party data (email, phone) is passed with each conversion event. Improves attribution accuracy 20-40% for cross-device users.

Data to hash + pass on every primary conversion:
- Email (SHA256, lowercased, whitespace-trimmed)
- Phone (SHA256, E.164, no spaces)
- First + last name (SHA256, lowercased)
- Country + zip (SHA256)

Server-side pass — never expose PII to the client.

---

## 4. Attribution model

**Google Ads:** Data-driven attribution (default in 2026). Requires:
- >300 conversions in the last 30 days across the account, OR
- Fall back to "Position-based" (40% first / 40% last / 20% middle) until threshold met

**GA4:** Set default attribution to "Data-driven" for the same conversion events.

**LinkedIn:** Post-click + post-view within 30-day window (default LinkedIn model). Do NOT dedupe against Google Ads — LinkedIn typically drives the awareness that Google captures as the click.

---

## 5. Consent / privacy

- Publish `klaravex.com/privacy` covering ad tracking cookies + GA4 + LinkedIn Insight.
- Consent Mode v2 on Google Ads: fire conversion pings only when consent granted.
- No PII shipped to LinkedIn without Consent Mode.
- Comply with California CCPA + CPRA opt-out link ("Do Not Sell or Share My Personal Information").

---

## 6. Wiring checklist for Anthony (or Loki once console access exists)

- [ ] GA4 property `Klaravex US` created (or verified) with a Google Tag Manager container
- [ ] Google Tag Manager container installed on every klaravex.com page (server-side + client-side hybrid recommended)
- [ ] GA4 events 2.1-2.8 defined + tested via GTM Preview mode
- [ ] Google Ads account linked to GA4 (T-AC-08)
- [ ] Conversions 2.1-2.7 imported into Google Ads
- [ ] Primary conversions: `readiness_review_booked` + `directive_quote_requested`
- [ ] Enhanced Conversions enabled + tested
- [ ] LinkedIn Insight Tag installed on every klaravex.com page (T-AC-14)
- [ ] LinkedIn conversion events: `Book_Appointment`, `Download`, `Lead`, `Contact` mapped
- [ ] Consent Mode v2 verified in Preview + on live
- [ ] `klaravex.com/privacy` published with ad-tracking disclosures
- [ ] End-to-end test: complete a real Readiness Review booking → verify event lands in GA4 within 30s → verify Google Ads reports it within 24h

---

## 7. Reporting layout (weekly review, T-AC-18)

Weekly ad performance dashboard (build in Looker Studio):

**KPIs:**
- Cost per primary conversion (Readiness Review + Directive Quote blended)
- Primary conversion count by ad group
- Secondary conversion count by ad group
- Click-through rate (CTR) by ad group + individual RSA
- Landing page bounce rate by ad group
- Quality Score by keyword (Google Ads)
- CTR + Conv rate by LinkedIn creative

**Auto-flag rules:**
- Any ad group with CPA >200% of target for 7 days → flag "consider pause"
- Any RSA with CTR <50% of ad group average → flag "consider rewrite"
- Any landing page with bounce >80% → flag "landing page audit"

---

## 8. Related tasks

- T-AC-01/02/03 — Google Ads account setup + auto-recommendations disabled → prerequisite
- T-AC-07 — Enhanced Conversions → depends on this spec being wired first
- T-AC-08 — GA4 ↔ Google Ads link → prerequisite for conversion imports
- T-AC-11 — Responsive Search Ads → will fire conversion events on click-through
- T-AC-12 — Google Ads extensions (sitelinks, callouts, call) → call extension depends on T14.9 phone number
- T-AC-14 — LinkedIn Insight Tag install → prerequisite for LinkedIn conversion mapping
- T-AC-16 — LinkedIn Document Ad + lead magnet → depends on `readiness_checklist_downloaded` event being live
- T-AC-18 — Weekly performance review → uses the dashboard defined in Section 7

---

*Draft for Anthony's review. Adjust conversion values (currently rough estimates based on typical MSP LTV), attribution windows, or dedup rules before wiring.*
