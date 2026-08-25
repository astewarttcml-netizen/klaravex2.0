# Ad platform setup — Meta, Google, LinkedIn

**Goal:** Provision API credentials for Meta Ads, Google Ads, and LinkedIn Ads so the Klaravex marketing race agents can autonomously create campaigns (in PAUSED state — agents never auto-spend without you tapping ✓ Approve in the inbox).

**Time estimates:** Meta ~30 min · LinkedIn ~1 hour + 1-2 day approval · Google ~2 hours + 1-3 day approval.

Do them in this order: Meta first (instant), LinkedIn second (faster approval), Google last (slowest approval).

---

## Meta (Facebook) Ads

### What you need at the end
Two values to paste into 1Password:
- `META_ADS_ACCESS_TOKEN` — system-user access token with `ads_management` scope
- `META_AD_ACCOUNT_ID` — your ad account ID, format `act_1234567890`

### Steps

1. **Go to Meta Business Manager**: https://business.facebook.com
2. **Confirm/create the Klaravex business account.** Top-left dropdown → Klaravex (or Create new business).
3. **Confirm/create an Ad Account.** Settings → Accounts → Ad Accounts.
   - If none exists: Add → Create New Ad Account. Name: "Klaravex US Ads". Currency USD. Time zone US/Pacific.
   - **Copy the Ad Account ID** (looks like `act_123456789012345`). Save it — that's `META_AD_ACCOUNT_ID`.
4. **Add a payment method.** Settings → Ad Accounts → [Klaravex US Ads] → Payment methods. Add Mercury card (Alpha card last4 `9125` OR Beta card last4 `0235` — pick one per ad account, OR create a second ad account so each race team has its own card).
5. **Create a System User for the API.** Settings → Users → System Users → Add.
   - Name: `Klaravex Marketing API`
   - Role: **Admin**
6. **Generate the access token.** On the System User row → Generate New Token.
   - App: pick the Klaravex Facebook App (or create one at https://developers.facebook.com/apps if you don't have one yet; type "Business")
   - Scopes (check all): `ads_management`, `ads_read`, `business_management`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`
   - Token type: **Never expires**
   - **Copy the token.** This is `META_ADS_ACCESS_TOKEN`.
7. **Assign the System User to the Ad Account.** Settings → Ad Accounts → [Klaravex US Ads] → Add People → select the System User → Manage campaigns.
8. **Save both values to 1Password** (Klaravex vault):
   - Update item `Social Media Tokens — IT Experts Berlin` (or create new `Klaravex Ad Tokens`):
     - Field `meta_ads_access_token`: paste token
     - Field `meta_ad_account_id`: paste `act_...`
9. **Tell Loki:** "I added Meta ad tokens to 1Password" — I'll push to Azure secrets.

### Sanity test
After Loki pushes the secret, the next marketing-race tick will be able to call `meta_ads_create_campaign`. Campaign starts PAUSED — verify in Ads Manager.

---

## LinkedIn Ads

### What you need at the end
- `LINKEDIN_ADS_ACCESS_TOKEN` — OAuth token with `r_ads`, `rw_ads`, `rw_ad_campaigns` scopes
- `LINKEDIN_AD_ACCOUNT_ID` — Sponsored Account URN, format `urn:li:sponsoredAccount:1234567`

### Steps

1. **Open LinkedIn Campaign Manager**: https://www.linkedin.com/campaignmanager
2. **Confirm/create the Klaravex sponsored ad account.**
   - If none exists: Create → Account name "Klaravex US". Currency USD. Associated Page: Klaravex (the company page, org URN `122373998`).
   - On the account dashboard, copy the numeric account ID from the URL (e.g. `https://www.linkedin.com/campaignmanager/accounts/123456789` → `123456789`).
   - **`LINKEDIN_AD_ACCOUNT_ID` = `urn:li:sponsoredAccount:123456789`** (wrap with the URN prefix).
3. **Add a payment method.** Campaign Manager → Settings → Billing → Add card. Use Mercury Alpha/Beta card (same logic as Meta — one account per race team if you want).
4. **Open the existing LinkedIn app** at https://www.linkedin.com/developers/apps
   - The `Klaravex` app (client_id starts `868ias…` per 1Password) should be there
   - Open it → **Products** tab → request access to:
     - **Marketing Developer Platform** (this unlocks Ads APIs)
     - **Advertising API** (this exposes the actual endpoints)
   - LinkedIn manually reviews this — usually 1-2 business days. Use the request notes:
     > "Klaravex is an AI-native managed IT services company. We will use the Ads API to programmatically create campaigns from our backend (Python + httpx) targeting B2B decision-makers at SMBs in legal, accounting, and medical industries. We will not display LinkedIn data off-platform and will not analyze data outside our own campaigns. All campaigns start in PAUSED state for human review before activation."
5. **Once approved**, generate an access token via the OAuth flow:
   - **Auth tab** → Authorization → Authorized redirect URLs → add `https://api.klaravex.com/api/v1/auth/linkedin/callback` (we'll wire that route if needed, or use a one-time manual token swap)
   - Easiest one-time approach: use LinkedIn's OAuth playground at https://www.linkedin.com/developers/tools/oauth/token-generator
   - Select your app → scopes: `r_ads`, `rw_ads`, `rw_ad_campaigns`, `r_ads_reporting`, `w_organization_social` (combine with the company-post scope while you're here)
   - **Copy the access token**.
6. **Save both values to 1Password** (`Social Media Tokens — IT Experts Berlin`):
   - `linkedin_ads_access_token`: paste token
   - `linkedin_ad_account_id`: paste `urn:li:sponsoredAccount:...`
7. **Tell Loki:** "LinkedIn ad tokens are in 1Password" — push to Azure.

### Sanity test
Next marketing tick after secret-push → agent calls `linkedin_ads_create_campaign` → see paused campaign in Campaign Manager.

---

## Google Ads

### What you need at the end
- `GOOGLE_ADS_DEVELOPER_TOKEN` — issued by Google after manual review
- `GOOGLE_ADS_CUSTOMER_ID` — your ad account ID (10 digits, no dashes), format `1234567890`
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID` — your MCC (manager) account ID, same format
- `GOOGLE_ADS_SERVICE_ACCOUNT_JSON` — full JSON content of a Google Cloud service account key with Google Ads API enabled

### Steps

1. **Open Google Ads** at https://ads.google.com
   - Sign in with the Klaravex Google account (workspace email)
   - If no ad account exists: skip the wizard and click "Create new account" → "Switch to Expert Mode" → Create campaign later
   - **Copy the Customer ID** from the top-right (10 digits, format `XXX-XXX-XXXX`). Strip dashes → that's `GOOGLE_ADS_CUSTOMER_ID`.
2. **Create an MCC (Manager Account)** at https://ads.google.com/intl/en_us/home/tools/manager-accounts/
   - Name: "Klaravex Manager"
   - **Copy the Manager Customer ID**. That's `GOOGLE_ADS_LOGIN_CUSTOMER_ID`.
3. **Link the regular ad account to the MCC.** From the MCC → Tools → Linked accounts → Link existing account → enter the regular account customer ID → invite → accept from the regular account.
4. **Apply for a Developer Token.** From the MCC → Tools → API Center → Apply for token.
   - Use case description (paste):
     > "Klaravex is an AI-native managed IT services company. Our backend (Python 3.11 / FastAPI, hosted on Azure Container Apps) uses the Google Ads API exclusively for first-party campaign management on our own ad accounts. We will programmatically create Search and Display campaigns, ad groups, keywords, and ads — all starting in PAUSED state for human review. We will read campaign performance for our own campaigns to inform internal optimization. We do not display Google Ads data off-platform, do not aggregate user data, and do not build third-party tools on top of the API. Expected request volume: under 1,000 mutate operations per day across both ad accounts combined. Read volume: under 10,000 requests per day. We will respect all rate limits and quota policies."
   - **Approval timeline: 1-3 business days for basic access, longer for standard access.**
5. **Create a Google Cloud Service Account for API access.**
   - Open https://console.cloud.google.com
   - Pick the Klaravex project (or create one named `klaravex-marketing`)
   - APIs & Services → Library → enable **Google Ads API**
   - APIs & Services → Credentials → Create Credentials → Service Account
     - Name: `klaravex-google-ads`
     - Role: **none** (the role is granted on the Google Ads side, not GCP)
   - On the new service account → Keys tab → Add key → JSON → **download the file**
6. **Authorize the service account in Google Ads.**
   - In Google Ads (MCC) → Tools → API Center → Add a new authorized user → paste the service account email (looks like `klaravex-google-ads@<project>.iam.gserviceaccount.com`) → Admin access
7. **Save creds to 1Password** (`Klaravex Ad Tokens`):
   - `google_ads_developer_token`: from step 4
   - `google_ads_customer_id`: 10-digit ad account ID
   - `google_ads_login_customer_id`: 10-digit MCC ID
   - `google_ads_service_account_json`: paste the entire JSON file content as a multi-line text field
8. **Tell Loki:** "Google Ads creds are in 1Password" — push to Azure.

### Sanity test
Next tick → agent calls `google_ads_create_campaign` → see paused campaign in Google Ads UI.

---

## Common rules across all three

- **All campaigns start PAUSED.** Agents never activate a campaign without you tapping ✓ Approve in `/admin/inbox/queue` for that specific action.
- **Daily budget cap is enforced server-side per team** (currently $50/day per team, configurable in `klaravex_marketing_teams.daily_spend_cap_usd`).
- **All ad spend appears on the Mercury virtual card** linked to that team. You'll see real-time transactions in Mercury.
- **Attribution:** every ad URL is `https://klaravex.com/?t=alpha` or `?t=beta`. Klaravex middleware tags every resulting client/lead with that source.

## After all creds are in place

Tell Loki: "All ad platform creds are in 1Password — push them and revive the marketing race ticks."

I'll:
1. Push every secret to Azure Container Apps via `az containerapp secret set`
2. Roll the revision so the env vars hydrate
3. Manually fire `POST /api/v1/internal/marketing/tick-all` to wake both agents
4. Schedule the tick endpoint via cron (Azure Logic App or Hetzner crontab) so it fires every 6 hours
5. Verify the first paused campaign appears in each platform's UI

After that the race is genuinely live. You watch the inbox + Mercury + platform dashboards, tap ✓ to unpause campaigns you want running.
