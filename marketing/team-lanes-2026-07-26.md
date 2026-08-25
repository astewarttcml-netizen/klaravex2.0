# Team Lane Rules — No Duplication

## The Problem
Both teams were generating content for the same platforms, same topics, same audience → duplicate posts, wasted approval bandwidth, confused messaging.

## The Fix: Channel Ownership

| Channel | Owner | Other team may NOT use |
|---------|-------|----------------------|
| **Google Ads** | Alpha | Beta cannot create Google campaigns |
| **Meta Ads** (Facebook/Instagram) | Alpha | Beta cannot create Meta campaigns |
| **LinkedIn Sponsored** | Alpha | Beta cannot boost LinkedIn posts |
| **LinkedIn Organic** | Beta | Alpha cannot post organic LinkedIn |
| **Twitter/X** | Beta | Alpha cannot post on X |
| **Reddit** | Beta | Alpha cannot post on Reddit |
| **HN / Dev communities** | Beta | Alpha cannot post on HN |
| **Email outreach** (Smartlead) | Alpha | Beta cannot send cold email |
| **Blog / SEO content** | Beta | Alpha cannot publish blog posts |
| **Referral programs** | Beta | Alpha cannot set up referral flows |

## Topic Ownership (prevents messaging overlap)

| Topic | Alpha angle | Beta angle |
|-------|------------|------------|
| **Scam recovery (free)** | Paid awareness ads (Google/Meta) | Organic thought leadership (LinkedIn/X/Reddit) |
| **B2B compliance** | Direct Google Ads → landing pages | Blog content + HN/Reddit authority building |
| **Consumer services** | Meta/IG consumer ads | Twitter threads + Reddit community engagement |
| **vCISO** | LinkedIn sponsored to decision-makers | LinkedIn organic case studies |
| **Marketing race itself** | (doesn't promote the race — Alpha just spends) | All race promotion is Beta's job |

## Enforcement

Add to each team's system prompt:

**Alpha prompt addition:**
```
CHANNEL RULES (binding):
You may ONLY use: Google Ads, Meta Ads, LinkedIn Sponsored, Smartlead email outreach.
You may NOT use: LinkedIn organic, Twitter/X, Reddit, HN, blog, referral programs.
If you draft content for a channel you don't own, it will be auto-rejected.
```

**Beta prompt addition:**
```
CHANNEL RULES (binding):
You may ONLY use: LinkedIn organic, Twitter/X, Reddit, HN, blog/SEO, referral programs.
You may NOT use: Google Ads, Meta Ads, LinkedIn Sponsored, Smartlead email outreach.
If you draft content for a channel you don't own, it will be auto-rejected.
```

## Code Enforcement

In `marketing_tools.py`, add a channel-ownership check before any action:

```python
ALPHA_CHANNELS = {"google_ads", "meta_ads", "linkedin_sponsored", "smartlead"}
BETA_CHANNELS = {"linkedin_personal", "linkedin_company", "twitter", "reddit", "blog", "referral"}

def _check_channel_ownership(team_code: str, channel: str) -> bool:
    if team_code == "alpha": return channel in ALPHA_CHANNELS
    if team_code == "beta": return channel in BETA_CHANNELS
    return False
```
