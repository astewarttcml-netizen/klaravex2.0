# Growth schedulers — systemd timers (NO Celery beat)

Cadence for Layer A streams is owned by **systemd timers** (or plain cron) that call the Growth API. Celery beat is explicitly out of this failure domain.

## Units

| File | Role |
|------|------|
| `growth-api.service` | **Persistent** FastAPI Layer C (`uvicorn` on `:4210`) — timers depend on this |
| `growth-stream@.service` | Oneshoot: `POST /v1/streams/%i/run` |
| `growth-stream@.timer` | Cadence template — edit `OnCalendar=` per stream |
| `growth-digest.service` / `.timer` | Daily **Nadia / Marco** accountability digests (`POST /v1/digests/generate`, 08:15). Nadia includes social growth KPIs + week theme from `charters/social-growth.md`. |
| `install-growth-api.sh` | Install + enable `growth-api.service` (user systemd) |
| `install-timers.sh` | Idempotent install stream timers (default: **user** timers) |

**Install order:** Growth API first, then stream timers.

```bash
./growth/schedulers/install-growth-api.sh
systemctl --user enable --now growth-api.service
./growth/schedulers/install-timers.sh
systemctl --user enable --now growth-stream@leads.timer   # etc.
```

Instance name = stream allowlist name, e.g. `growth-stream@leads.timer`.

## Install (default: user timers)

```bash
cd /home/anthony/Klaravex2.0
# ensure growth/.env has GROWTH_INTERNAL_SECRET and GROWTH_API_BASE (optional)
./growth/schedulers/install-timers.sh
# enable one stream after Phase 2+ :
systemctl --user daemon-reload
systemctl --user enable --now growth-stream@leads.timer
systemctl --user list-timers 'growth-stream@*'
```

Requires lingering for headless user sessions: `loginctl enable-linger "$USER"`.

## Per-stream cadence (drop-ins required)

The template timer has **no** default `OnCalendar` — each stream needs a drop-in under `~/.config/systemd/user/growth-stream@<stream>.timer.d/override.conf`. Clear any inherited calendar first:

```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 06:15:00
```

| Stream | Cadence | Local time (**America/New_York**) |
|--------|---------|------------|
| `leads` | Mon–Fri | 06:15 ET |
| `socials` | Daily (7 days; Sat–Sun B2C-focused) | 06:30 ET |
| `seo-blog` | Mon–Fri | 06:45 ET |
| `freelance` | Hourly (24/7) | `:00` every hour |
| `gatekeeper` | Mon–Fri (after upstream) | 08:00 ET |
| `ads` | Weekly Mon | 07:15 ET |
| `backlinks` | Weekly Wed | 07:15 ET |
| `kb` | Mon/Wed/Fri | 07:30 ET |
| `forums` | Mon/Wed/Fri | 07:45 ET |
| digests | Mon–Fri | 08:15 ET |

Ensure `growth/.env` sets `GROWTH_API_BASE=http://127.0.0.1:4210` (or your Growth API port)
and **`GROWTH_TIMEZONE=America/New_York`** (Eastern — ops + B2B) plus
**`GROWTH_TIMEZONE_WEST=America/Los_Angeles`** (Pacific — B2C publish).
Timer `OnCalendar` lines include `America/New_York` so agent runs are Eastern
wall-clock regardless of the host TZ.

Default organic publish slots when scheduling (not `--publish-now`):
**10:00 AM Eastern (B2B)** and **10:00 AM Pacific (B2C)**.

## System-wide alternative

```bash
INSTALL_SCOPE=system ./growth/schedulers/install-timers.sh
# units land in /etc/systemd/system — needs root
sudo systemctl daemon-reload
sudo systemctl enable --now growth-stream@leads.timer
```

## Explicit non-goals

- Do **not** register Growth streams on Celery beat.
- Do **not** shell Claude from the timer without going through Growth API (ledger / kill switch).
- Do **not** put secrets in the unit file body — use `EnvironmentFile=` pointing at `growth/.env`.
