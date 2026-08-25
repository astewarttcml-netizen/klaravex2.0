# X (Twitter) API setup

**Goal:** Get OAuth 1.0a credentials so the Klaravex backend can programmatically post to the `@klaravex` X account.

**Time estimate:** 30-45 min setup + immediate access (no manual review on Basic tier).

**Cost:** Basic tier = **$200/month**. The Free tier is read-only on tweets and limited to 1500 writes/month with no media uploads — not enough for our use case. Don't waste time on Free.

---

## What you need at the end

Four values to paste into 1Password (Klaravex vault → item `Social Media Tokens — IT Experts Berlin` or new `Klaravex X / Twitter API`):

| Field | Where you get it |
|---|---|
| `TWITTER_API_KEY` | Developer Portal → your App → Keys and tokens → Consumer Keys → API Key |
| `TWITTER_API_SECRET` | Same screen, just below |
| `TWITTER_ACCESS_TOKEN` | Same screen, Access Token and Secret section |
| `TWITTER_ACCESS_TOKEN_SECRET` | Same screen, immediately after |

---

## Pre-requisite: rename the X handle to @klaravex

Per earlier conversation, the X handle is still on the legacy `IT Experts Berlin` branding. **Do this first**, otherwise your API tokens will tie to the old name and you'll have to re-do the OAuth dance after renaming.

1. Sign in to https://x.com with the existing account
2. Settings → Account → Username → change to `klaravex` (or `klaravexllc` / `klaravex_io` if taken)
3. Update display name to `Klaravex`
4. Update bio + profile picture + header to match Klaravex brand

---

## Step-by-step

### 1. Sign up for X Developer access

1. Go to https://developer.x.com (NOT developer.twitter.com — that redirects but the canonical URL is x.com now)
2. Sign in with the Klaravex X account
3. Click "Sign up" or "Get started"
4. **Pick Basic tier ($200/mo)**, not Free
   - Free tier limits: 1500 writes / month, NO read on tweets, NO media uploads, NO threads, NO mentions reading. Useless for what we need.
   - Basic tier: 50,000 writes / month, 10,000 reads / day, OAuth 1.0a + 2.0 supported, media uploads OK. **This is the right fit.**
   - Pro tier ($5,000/mo): only worth it if we hit the 50k writes ceiling, which we won't for a long time.
5. Pay with the Klaravex Mercury card

### 2. Fill out the application

You'll be asked a series of questions. Honest answers, no embellishment:

**"What's your use case?"**
> Klaravex is an AI-native managed IT services company. We will use the X API exclusively for first-party content publishing on our own brand accounts (@klaravex and the founder's personal account). We are not building a third-party X client, analytics product, or any application that surfaces X data to external users.

**"Describe all of your use cases of X's data and API"**
> 1. **Organic posting from our brand account.** Programmatic posting of text, images, and threads to the official Klaravex X account using POST /2/tweets. Expected volume: 1-3 tweets per day on weekdays, occasional reply engagement when our content is discussed. All content is original, brand-owned, and reviewed by a human (the founder) through an internal approval queue before publishing.
>
> 2. **Founder's professional account.** Same scope as above for the founder's personal account, used for build-in-public commentary on building an AI-native IT services company. Same review queue, same publishing endpoint.
>
> 3. **Engagement reporting on our own tweets.** Programmatic reads of impressions, engagements, and reply counts for posts we have published, using GET /2/tweets/:id and the tweets/search/recent endpoint scoped to our own author ID. This data is used solely to inform our internal content calendar.
>
> 4. **Mention and reply monitoring for customer support.** Programmatic reads of @klaravex mentions via GET /2/users/:id/mentions so our team can respond to customer support inquiries that arrive via X.
>
> We will not bulk-scrape user data, build user profiles, sell or share X data, display X content off-platform, or use the API to train AI models.

**"Will you make X content/data available to a government entity?"** → No
**"Will you display X content or data off of X?"** → No
**"Will you analyze X content/data?"** → Only engagement metrics on our own published posts, for internal content planning

### 3. Create an App

1. Once approved (Basic tier is instant — no review wait), go to Developer Portal → Projects & Apps
2. Click "Add App" inside the default Project
3. App name: `Klaravex` (or `Klaravex Production` if you want to leave room for a dev app later)
4. Save the name

### 4. Configure App permissions for posting

This is the step that most people miss and then can't post.

1. On the new App → "User authentication settings" → click "Set up"
2. App permissions: **Read and Write** (NOT just Read)
3. Type of App: **Web App, Automated App or Bot**
4. App info:
   - Callback URI: `https://api.klaravex.com/api/v1/auth/x/callback` (we'll wire this if needed; one-time tokens won't actually use it)
   - Website URL: `https://klaravex.com`
   - Terms of service: `https://klaravex.com/terms`
   - Privacy policy: `https://klaravex.com/privacy`
5. Save

### 5. Generate the four tokens

1. Stay on your App → "Keys and tokens" tab
2. Under **Consumer Keys** → API Key and Secret → click "Regenerate" if needed → **copy both immediately** (the secret is shown only once)
   - These become `TWITTER_API_KEY` and `TWITTER_API_SECRET`
3. Under **Authentication Tokens** → Access Token and Secret → click "Generate"
   - **Copy both immediately**
   - These become `TWITTER_ACCESS_TOKEN` and `TWITTER_ACCESS_TOKEN_SECRET`

⚠️ **If you generated the Access Token BEFORE setting permissions to Read+Write**, the token will only have Read scope. Regenerate it AFTER changing permissions, otherwise posting will return 403.

### 6. Save to 1Password

In Klaravex vault → `Social Media Tokens — IT Experts Berlin` (yes the name is still stale, doesn't matter):

| 1Password field | Value |
|---|---|
| `twitter_api_key` | API Key from step 5.2 |
| `twitter_api_secret` | API Secret from step 5.2 |
| `twitter_access_token` | Access Token from step 5.3 |
| `twitter_access_token_secret` | Access Token Secret from step 5.3 |

### 7. Tell Loki

Message: "X API tokens are in 1Password"

I'll:
1. Push all four to Azure secrets via `az containerapp secret set`
2. Roll the revision so the env vars hydrate
3. Test by posting one harmless test tweet ("Klaravex is online.") then deleting it
4. Confirm `ACTIVE_PLATFORMS` in the backend now includes `twitter`

---

## Why we can't shortcut this with OAuth 2.0 only

OAuth 2.0 with PKCE is supported on X but:
- Tokens expire every 2 hours, refresh tokens every 6 months
- The library code in `social_media._publish_twitter` already uses OAuth 1.0a (which is the right call for server-side automation that posts on behalf of a static account — you generate once, use forever)
- Switching to OAuth 2.0 means refresh-token rotation, error handling, scope storage — 100+ lines of new code for zero functional benefit on a single-account use case

Stick with OAuth 1.0a.

---

## Sanity test after Loki pushes secrets

Once secrets are in Azure, the next time the social-media draft pipeline tries to post to `twitter`, the call hits the real API instead of returning "twitter credentials not configured". You can manually trigger this via:

```bash
curl -X POST https://api.klaravex.com/api/v1/internal/social/publish \
  -H "X-Loki-Secret: $LOKI_INTERNAL_SECRET"
```

(Assuming you have an approved Twitter draft in the inbox.)

A successful post returns the tweet URL `https://twitter.com/klaravex/status/<id>`. Anything else is an error — share the response with me and I'll diagnose.

---

## Common gotchas

| Symptom | Cause | Fix |
|---|---|---|
| 403 Forbidden on POST /2/tweets | Access Token generated BEFORE permissions set to Read+Write | Regenerate the Access Token after toggling permissions |
| 401 Unauthorized | Clock skew between server and X (rare on Azure but happens) | Verify Azure container time sync — should be NTP-correct automatically |
| 429 Too Many Requests | Basic tier 50K/month write cap hit | Probably won't happen for at least a year at our volume; if it does, upgrade to Pro |
| Tweet posts but no media | Media upload uses a different endpoint and chunked-upload protocol (not currently wired) | Add later when we want image tweets — separate task |

---

## What this does NOT cover

- **Image attachments on tweets** — separate work. X requires chunked media upload via `POST /1.1/media/upload.json` before referencing the media ID in the tweet. The current `_publish_twitter` is text-only. When we want image tweets we'll add media support — about 100 lines of additional code.
- **Polls, threads, scheduled posts** — also future. Each is its own endpoint.
- **Auto-responding to mentions** — read API works but auto-reply is a separate workflow + abuse risk.

For now: text-only posts from one account. That's the floor we're aiming for.
