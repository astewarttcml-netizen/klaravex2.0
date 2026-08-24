# Phase 6 — Klaravex Klara AI backend deploy runbook

This runbook turns the code in `infra/loki-handlers/` into a live operational
backend at `https://api.klaravex.com/`. Built by Klara AI iteration 2; verified by
the smoke tests in `tests/`.

## 1. Apply the schema

Run the migration against the shared Cloud86 Postgres (klaravex_ prefix is
already encoded in every table name):

```bash
psql "$DATABASE_URL" -f infra/loki-handlers/migrations/001_klaravex_core.sql
```

Creates six tables:
- `klaravex_clients`
- `klaravex_tickets`
- `klaravex_portal_tokens`
- `klaravex_hours_ledger`
- `klaravex_escalations`
- `klaravex_kb_chunks`

Safe to re-run: every CREATE is `IF NOT EXISTS`.

## 2. Set environment variables

Edit `/opt/loki/envs/.env.klaravex` on Hetzner. The template at
`infra/.env.klaravex.template` already declares the keys; fill in:

```bash
# Required for portal + handlers
DATABASE_URL=postgresql://...lend.your-database.de:5432/dediviac_db0
RESEND_API_KEY=re_...
PORTAL_BASE_URL=https://klaravex.com/portal
LOKI_INTERNAL_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Required for escalations (else escalation rows persist but no alert is sent)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Optional — enables semantic KB search (else falls back to tsvector)
OPENAI_API_KEY=sk-...
```

## 3. Mount the routers in the FastAPI app

In the Klara AI backend app entrypoint (e.g. `app/main.py`), add:

```python
from klara.handlers.stripe_webhook import router as stripe_router
from klara.handlers.intake_consumer import router as intake_consumer_router
from klara.handlers.intake_b2b import router as intake_b2b_router
from klara.handlers.smartlead_webhook import router as smartlead_router
from klara.handlers.calendly_webhook import router as calendly_router
from klara.handlers.portal import router as portal_router

app.include_router(stripe_router, prefix="/api/v1/stripe")
app.include_router(intake_consumer_router, prefix="/api/v1/intake")
app.include_router(intake_b2b_router, prefix="/api/v1/intake")
app.include_router(smartlead_router, prefix="/api/v1/smartlead")
app.include_router(calendly_router, prefix="/api/v1/calendly")
app.include_router(portal_router, prefix="/portal")
```

(The package is imported as `klara.handlers`; add `Klaravex2.0` to
`PYTHONPATH` so `klara` resolves.)

Backend dependencies required (add to requirements.txt):

```
asyncpg>=0.29
fastapi>=0.110
httpx>=0.27
jinja2>=3.1
pydantic[email]>=2.7
stripe>=8.0
```

## 4. Wire nginx / Cloudflare for `klaravex.com/portal/`

Klaravex.com is WordPress (Cloud86). Two options:

**Option A — subdomain (recommended):** point `portal.klaravex.com` at the
Hetzner backend and serve everything from there. Set
`PORTAL_BASE_URL=https://portal.klaravex.com` and update the WP main-nav link.

**Option B — path-based reverse proxy:** add an nginx location block on
Cloud86 (Plesk → Apache & nginx Settings → Additional nginx directives) that
proxies `/portal/` to `https://api.klaravex.com/portal/`. PORTAL_BASE_URL
stays `https://klaravex.com/portal`.

## 5. Reindex the knowledge base

After backend boot, trigger an initial KB ingest:

```bash
curl -X POST https://api.klaravex.com/portal/internal/kb/reindex \
  -H "X-Loki-Internal-Secret: $LOKI_INTERNAL_SECRET"
```

Expected response:
```json
{ "pages_indexed": 8, "chunks_total": 47, "chunks_with_embeddings": 47 }
```

(Numbers vary by KB size; `chunks_with_embeddings` is 0 if OPENAI_API_KEY is
unset — search will fall back to Postgres full-text via tsvector.)

## 6. Smoke-test the four PRD §6 acceptance criteria

```bash
# (a) Portal loads
curl -I https://klaravex.com/portal/ | head -1
# expect: HTTP/2 302 (redirects to /portal/login)

# (b) Ticket row written (use the intake form, then query)
curl -X POST https://api.klaravex.com/api/v1/intake/consumer \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Test","email":"smoketest@klaravex.com","primary_issue":"verification","urgency":"low"}'
psql "$DATABASE_URL" -c "SELECT id, subject FROM klaravex_tickets ORDER BY created_at DESC LIMIT 1;"

# (c) KB lookup returns cited answer
curl -X POST https://api.klaravex.com/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message":"How do I set up MFA?","client_email":"smoketest@klaravex.com"}'
# expect: response mentions a knowledge-base article (citation block present)

# (d) Escalation queue receives test escalation
# Easiest path: open a ticket with urgency=emergency via the intake form.
curl -X POST https://api.klaravex.com/api/v1/intake/consumer \
  -H "Content-Type: application/json" \
  -d '{"name":"Esc Test","email":"escalation@klaravex.com","primary_issue":"test","urgency":"emergency"}'
# expect: Telegram message + Resend email; row in klaravex_escalations.
psql "$DATABASE_URL" -c "SELECT id, severity, delivered_via FROM klaravex_escalations ORDER BY created_at DESC LIMIT 1;"
```

## 7. Verify in the portal

1. Visit https://klaravex.com/portal/ — should redirect to `/portal/login`.
2. Enter your email; click the magic link in the inbox.
3. Dashboard should show the smoke-test tickets created in step 6.
4. `/portal/tickets` shows the full list.
5. `/portal/docs` lists indexed KB articles.

If any step fails, check `journalctl -u loki-klaravex.service -f` on Hetzner.
