# T-AC-06 · Google Ads + GA4 + GTM Console Wiring — 2026-07-15

**Prereq (already done):**
- GTM container `GTM-NZCXL7ZC` live on klaravex.com ✅
- GA4 property `G-GD0J1YFXHG` live on klaravex.com ✅
- Backend endpoints live on klaravex-api ✅ (this session)
  - `POST /readiness-review/submit` → fires `readiness_review_booked` ($250)
  - `POST /directive/request-pricing` → fires `directive_quote_requested` ($500)

**What's left = console clicks. Order matters — top-to-bottom.**

---

## 1. GA4 → Measurement Protocol API secret (2 min)

Google Analytics 4 → **Admin** → **Data Streams** → click the web stream (klaravex.com) → **Measurement Protocol API secrets** → **Create**.
- Nickname: `klaravex-api-server-side`
- Copy the generated secret.

Add to Azure Container App env vars (klaravex-api):
```
GA4_MEASUREMENT_ID=G-GD0J1YFXHG
GA4_API_SECRET=<paste secret>
GA4_MP_DEBUG=0
```
Optional Calendly redirect override (only if not using default):
```
CALENDLY_READINESS_REVIEW_URL=https://calendly.com/klaravex/readiness-review
```
Restart klaravex-api. Verify:
```
curl https://api.klaravex.com/readiness-review/health
curl https://api.klaravex.com/directive/health
```
Both should return `{"handler":..., "status":"ok"}`.

---

## 2. Register 8 conversion events in GA4 as conversions (5 min)

GA4 → **Admin** → **Events** → wait for first fire OR use **Create event** to declare in advance.

Mark these as **Conversions** (toggle on):

| Event name | Tier | Value hint |
|---|---|---|
| `readiness_review_booked` | Primary | 250 USD |
| `directive_quote_requested` | Primary | 500 USD |
| `readiness_assessment_completed` | Secondary | 50 USD |
| `readiness_checklist_downloaded` | Secondary | 30 USD |
| `contact_form_submitted` | Secondary | 75 USD |
| `phone_call_qualified` | Secondary | 150 USD |
| `chat_conversation_started` | Secondary | 40 USD |
| `newsletter_subscribed` | Micro | 5 USD |

For the 2 primaries: values are already sent from the backend (in the `value` event param). GA4 will use them automatically.

---

## 3. Link Google Ads ↔ GA4 (3 min)

GA4 → **Admin** → **Product links** → **Google Ads links** → **Link** → pick Klaravex Google Ads account → enable **Personalized advertising** + **Auto-tagging**.

---

## 4. Import GA4 conversions into Google Ads (5 min)

Google Ads → **Tools & Settings** → **Conversions** → **New conversion action** → **Import** → **Google Analytics 4 properties** → tick all 8 events above → **Import and continue**.

Then for each imported action:
- `readiness_review_booked`: set **Primary** action, category = "Submit lead form", counting = "One" per click, click-through window = 30 days.
- `directive_quote_requested`: set **Primary** action, category = "Submit lead form", counting = "One" per click, 30-day window.
- All 6 secondaries: set **Secondary** action (observation-only; do not feed Smart Bidding).

---

## 5. Enhanced Conversions (3 min)

Google Ads → **Tools & Settings** → **Conversions** → click `readiness_review_booked` → **Settings** → **Enhanced conversions** → **Turn on** → source = **Google Tag or Google tag Manager** — but since our fires are server-side, choose **Google Ads API** → confirm hashed PII (email, phone, first_name, last_name, country, postal_code) is passing from server (klaravex-api sends `user_data` block on every MP call — already implemented).

Repeat for `directive_quote_requested`.

Google Ads will show a diagnostic score within 24-48h once real events flow.

---

## 6. GTM tags for 6 client-side secondary events (~15 min)

GTM → workspace on `GTM-NZCXL7ZC` → for each event below: **Tags** → **New** → **Google Analytics: GA4 event** → configuration tag = `G-GD0J1YFXHG` → trigger as specified. **Publish** at the end.

### 6.1 `readiness_assessment_completed`
- Trigger: Custom Event, event name = `readiness_score_submitted` (assessment page fires this via `dataLayer.push({event: 'readiness_score_submitted', score, red_domains})`).
- Event parameters: `value=50`, `currency=USD`, `score={{DLV - score}}`, `red_domains={{DLV - red_domains}}`.
- DLV vars: create Data Layer Variable `DLV - score`, `DLV - red_domains`.

### 6.2 `readiness_checklist_downloaded`
- Trigger: Page View, matches Regex `/thanks/readiness-checklist$`.
- Params: `value=30`, `currency=USD`, `download_source=site`.
- Additional trigger: Custom Event `linkedin_lead_form_submit` for LinkedIn-sourced (fires from LinkedIn Marketing API webhook → dataLayer push on redirect landing).

### 6.3 `contact_form_submitted`
- Trigger: Form Submission on `/contact*` (built-in trigger; enable "Wait for tags", 2000 ms; validation on).
- Params: `value=75`, `currency=USD`, `form_id={{Form ID}}`, `source_page={{Page Path}}`.
- **Dedup rule (implement as blocking trigger):** create blocking trigger `Recent readiness booking` = Custom JS variable that reads sessionStorage flag set by `readiness_review_booked` client-side helper (see §6.7). If flag < 30 min old, block this tag.

### 6.4 `phone_call_qualified`
- Skip in GTM — this is server-side (klaravex-api receives Vapi call-completion webhook → fires MP event). Add to backlog: `infra/loki_handlers/vapi/webhook_call_event.py` fires MP `phone_call_qualified` with `value=150` when call.duration_seconds > 60 AND lead qualified.

### 6.5 `chat_conversation_started`
- Trigger: Custom Event `klaravex_chat_started` (chat widget fires this after 3 message exchanges).
- Params: `value=40`, `currency=USD`, `topic={{DLV - chat_topic}}`.

### 6.6 `newsletter_subscribed`
- Trigger: Form Submission on any form with class `newsletter-subscribe` OR page view on `/thanks/newsletter`.
- Params: `value=5`, `currency=USD`, `source_page={{Page Path}}`.

### 6.7 Client-side helper — mirror server-side primary fires
Add a **Custom HTML tag** in GTM firing on Custom Event `readiness_booking_success` (which the frontend triggers on the API 200 response):
```html
<script>
  try {
    sessionStorage.setItem('klx_recent_readiness_booking', String(Date.now()));
  } catch(e) {}
</script>
```
This lets the `contact_form_submitted` tag dedup as specified.

---

## 7. LinkedIn Insight Tag + conversion mapping (10 min)

LinkedIn Campaign Manager → **Analyze** → **Insight Tag** → **Manage Insight Tag** → copy the partner ID.

Add to GTM: **Tags** → **New** → **LinkedIn Insight** template → paste partner ID → trigger = All Pages. **Publish**.

LinkedIn Campaign Manager → **Analyze** → **Conversions** → create these:
| LinkedIn conversion name | Type | Value | Fires on |
|---|---|---|---|
| Book_Appointment | Book appointment | $250 | Custom Event → same trigger as GA4 `readiness_review_booked` (server-to-server via LinkedIn Conversions API in a future task, or client-side via GTM tag firing on `readiness_booking_success` dataLayer event) |
| Download | Download | $30 | Custom Event → `readiness_checklist_downloaded` |
| Lead | Lead | $500 | Custom Event → `directive_quote_requested` |

---

## 8. Consent Mode v2 (5 min)

GTM → **Templates** → **Search Gallery** → install **Cookiebot** OR **Consentmanager** template (whichever aligns with existing Cookie Law Info plugin on WP).

Set up Consent Initialization tag (fires **before** anything else):
- `ad_storage`: denied by default
- `analytics_storage`: denied by default
- `ad_user_data`: denied
- `ad_personalization`: denied
- On user acceptance → `dataLayer.push({event: 'consent_granted', ad_storage: 'granted', analytics_storage: 'granted', ad_user_data: 'granted', ad_personalization: 'granted'})`.

All GA4 + Google Ads + LinkedIn tags: set **Consent settings** → **Require additional consent for tag to fire** → require `ad_storage` + `analytics_storage`.

Verify: GTM Preview mode → confirm tags don't fire before consent, do fire after.

---

## 9. Privacy page (5 min)

Publish `klaravex.com/privacy` if not already live. Must cover:
- What data is collected (name, email, phone, firm, IP, browsing behavior)
- Cookies / analytics disclosure (GA4, LinkedIn Insight, GTM)
- Ad-personalization opt-out link
- California CCPA/CPRA rights section
- Contact for data deletion requests: `privacy@klaravex.com`

Link from footer sitewide (Cookie Law Info plugin already handles this).

---

## 10. End-to-end test (10 min)

1. Open GA4 → **Reports** → **Realtime**.
2. Open GTM in Preview mode → connect to klaravex.com.
3. Trigger `readiness_review_booked`:
   ```
   curl -X POST https://api.klaravex.com/readiness-review/submit \
     -H 'Content-Type: application/json' \
     -d '{"email":"test-conv@klaravex.com","first_name":"Test","last_name":"Conv",
          "phone_e164":"+15550000001","vertical":"legal","utm_source":"google_ads",
          "utm_medium":"cpc","utm_content":"test_ad_group","ga_client_id":"test.1234"}'
   ```
4. GA4 Realtime should show `readiness_review_booked` within ~30 seconds. Google Ads conversion column should show +1 within ~24h.
5. Repeat for `/directive/request-pricing` with `firm_size` + `regulator` set.
6. Fill contact form on klaravex.com → GTM Preview should show `contact_form_submitted` tag firing (with dedup off if no recent booking).

If any step misses, check: env vars set, secret valid (GA4 debug endpoint), tag published in GTM (not just saved), conversion imported in Google Ads.

---

## 11. Reporting dashboard (Looker Studio) — deferred

Per spec §8, build a 6-KPI Looker Studio dashboard: cost per primary conversion, counts by type/ad group, CTR by ad group, landing page bounce, Quality Score. Auto-flag rules: CPA >200% target, RSA CTR <50% avg, LP bounce >80%. Task = **T-AC-18 weekly review** (dependent on 30 days of data).

---

## What Loki / Anthony still owes after this doc

- LinkedIn Conversions API server-to-server (parity with server-side GA4 fires) — deferred, LinkedIn client-side is acceptable interim.
- Vapi call-event webhook → MP fire for `phone_call_qualified` — one-file addition to `infra/loki_handlers/vapi/webhook_call_event.py`.
- Conversion-value tuning after 30 days of pipeline data (obs #16408 flagged $250 / $500 as estimates; Directive LTV suggests ~$1,500 initial value).
