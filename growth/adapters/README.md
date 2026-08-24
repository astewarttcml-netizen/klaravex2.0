# Growth adapters (Phase 5)

External tool boundary for Layer C. klaravex-os **never** calls these directly — only via Growth API.

| Adapter | Streams | Env keys | Live I/O |
|---------|---------|----------|----------|
| `hunter` | leads | `HUNTER_API_KEY` | **connected** — find/verify in leads pipeline (`hunter_enrich.py`) |
| `clay` | leads | `CLAY_API_KEY` | stub (optional waterfall / no-code tables) |
| `taplio` | socials | `TAPLIO_API_KEY` | **connected** — draft/schedule via REST + `socials_dispatch.py` |
| `zernio` | socials (TikTok/YouTube) | `ZERNIO_API_KEY` in `~/.config/social/.env` | **wired** — drafts via `zernio_dispatch.py` |
| `ads` | ads | Google OAuth + Meta + LinkedIn tokens in `growth/.env` | **connected** — probe + weekly report pull (`ads_pull.py`) into `outbox/ads/inputs/` (read-only; no spend) |
| `smartlead` | leads, freelance | `SMARTLEAD_API_KEY`, `SMARTLEAD_MASTER_CAMPAIGN_ID` | **connected** — probe + APPROVED dispatch (`leads_dispatch.py`) |
| `wordpress` | seo-blog, kb | `WP_SITE_URL`, `WP_APP_PASSWORD`, `WP_APP_USER` | **connected** — draft via REST + `content_dispatch.py` |
| `upwork` | freelance | OAuth (`UPWORK_CLIENT_ID` / `UPWORK_CLIENT_SECRET`) + GraphQL | **official API** — Connections → Authorize; cookie vault is fallback only |
| `guru` | freelance | session cookie vault (`GURU_SESSION_COOKIE`) | **session** — no bid API; cookie enables scout |
| `peopleperhour` | freelance | session cookie vault (`PPH_SESSION_COOKIE`) | **session** — no bid API; cookie enables scout |

## API

- `GET /v1/adapters` — probe all (status: `poc_sandbox`, `ready`, `stub`, `connected`, `error`)
- `POST /v1/adapters/{name}/invoke` — sandbox invoke; logged to run ledger
- `GET /v1/sessions` / `GET|PUT|DELETE /v1/sessions/{upwork|guru|peopleperhour}` — cookie vault + live probe (cookie values never returned)
- `GET /v1/upwork/status` / `PUT /v1/upwork/oauth/credentials` / `GET /v1/upwork/oauth/start` / `POST /v1/upwork/oauth/callback` / `POST /v1/upwork/search` — official GraphQL job search

Create the Upwork app at https://www.upwork.com/developer/keys/apply (OAuth 2.0, callback `http://127.0.0.1:4100/api/oauth/upwork/callback`, permission **Read marketplace Job Postings**). Then Connections → Upwork → Authorize.

Headed login (writes the vault, mirrors worker `.env`):

```bash
cd /home/anthony/Klaravex2.0
.venv/bin/python -m growth.sessions.login upwork
```

Credentials read from `GROWTH_ADAPTER_ENV_FILE` / worker `.env`, plus `growth/.env` (ads tokens). Values are never returned in API responses.

### Ads pull (read-only)

```bash
cd /home/anthony/Klaravex2.0
PYTHONPATH=. .venv/bin/python -m growth.outreach.ads_pull --probe-only
PYTHONPATH=. .venv/bin/python -m growth.outreach.ads_pull --days 7
```

Writes `revenue-agents/outbox/ads/inputs/YYYY-MM-DD-performance.md` (+ JSON sidecar). No campaign create/enable — proposals stay human-gated.
