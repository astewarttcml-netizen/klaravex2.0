# Klara AI Watchdog — Install & Operations Runbook

**Objective:** Detect failures across the Klara AI estate every 30 minutes and self-heal
with a bounded `restart → restart → rebuild` ladder, escalating to an alert when a
component is genuinely stuck — without inducing scheduled downtime.

**Author:** generated for Anthony · **Status:** artifacts only — NOT yet deployed.
Nothing in this package has been run against production.

---

## 1. Scope, and an honest limitation

You asked to "check all agents and systems and rebuild every 30 min." The estate spans
**three different control planes**, and no single job can heal all three. This package
implements the two that can actually be healed, plus monitoring for the third.

| Layer | What it is | Mechanism | Self-heal possible? |
|------|------------|-----------|---------------------|
| 1. Cloud86 SecondBrain | `loki-postgres`, `loki-ollama`, `loki-vault-mcp` containers | On-host systemd watchdog (this package) | **Yes** — restart/rebuild |
| 1. Hetzner Klara AI backend | Klara AI app container(s) on CX22 | Same watchdog, deployed a 2nd time, host-tuned | **Yes** — restart/rebuild |
| 2. Cowork scheduled agents | Claude desktop scheduled tasks | External liveness check only | **No** — not containers; can re-trigger/alert, not "rebuild" |

**Why per-host, not one central healer:** self-heal must run on the same host as the
thing it heals. A central healer that SSHes out loses the ability to heal during the
exact failure you care about most — a network partition. Each host runs its own
watchdog; alerts are centralized to one webhook.

**Why not unconditional rebuild every 30 min (your original phrasing):** it would drop
in-flight MCP/SSE connections and kill embedding work every cycle, and `docker compose
build` recompiles images — on a timer that churns images and risks pulling a broken
`:latest`. Docker's existing `restart: unless-stopped` already covers crashes. This
watchdog targets the gap Docker can't see: **alive-but-broken** (503s, stalled worker,
missing model). Rebuild fires only after restarts fail.

---

## 2. Files in this package

| File | Installs to | Purpose |
|------|-------------|---------|
| `loki-watchdog.sh` | `/usr/local/sbin/loki-watchdog.sh` | The healer |
| `loki-watchdog.service` | `/etc/systemd/system/` | One-shot unit |
| `loki-watchdog.timer` | `/etc/systemd/system/` | 30-min trigger |
| `loki-watchdog.env.example` | `/etc/loki-watchdog.env` | Per-host config |

---

## 3. What it checks and what each result proves

| Service | Probe | Proves | Heals if it fails |
|---------|-------|--------|-------------------|
| postgres | `pg_isready` in `loki-postgres` | DB accepts connections (not just process up) | `up -d → restart×2 → rebuild` |
| ollama | `ollama list` contains the model | Daemon serving AND embedding model loaded | pull model first; then ladder |
| vault-mcp | `GET /health` → `status:healthy` + `db:true` | App serving and DB-connected | ladder |
| worker | oldest `pending` in `note_submissions` < threshold | Embedding pipeline is draining, not wedged | restart vault-mcp (resets worker) |

Probes run in dependency order (db → ollama → mcp) so the watchdog doesn't restart
vault-mcp for a failure that's really Postgres or Ollama.

---

## 4. Install (per host)

> Run on **Cloud86 first**, validate, then repeat on **Hetzner** with Host B config.

```bash
# 4.1 Copy artifacts onto the host
sudo install -m 0755 loki-watchdog.sh /usr/local/sbin/loki-watchdog.sh
sudo install -m 0644 loki-watchdog.service /etc/systemd/system/loki-watchdog.service
sudo install -m 0644 loki-watchdog.timer   /etc/systemd/system/loki-watchdog.timer

# 4.2 Create the config (edit the correct host block, then lock it down)
sudo cp loki-watchdog.env.example /etc/loki-watchdog.env
sudo nano /etc/loki-watchdog.env        # set HOST_LABEL, WEBHOOK_URL, MCP_API_KEY, toggles
sudo chmod 600 /etc/loki-watchdog.env   # may contain the MCP API key

# 4.3 State dir
sudo mkdir -p /var/lib/loki-watchdog

# 4.4 Dry run BEFORE arming the timer — confirm it reports healthy, heals nothing
sudo /usr/local/sbin/loki-watchdog.sh; echo "exit=$?"
#   exit=0 expected on a healthy host. Watch the lines: each service => "healthy".

# 4.5 Arm the timer
sudo systemctl daemon-reload
sudo systemctl enable --now loki-watchdog.timer
```

**Why this order matters:** step 4.4 runs the healer by hand so a misconfig (wrong
container name, wrong health port, bad API key) surfaces as a log line you read — not as
a 3am restart loop after the timer is live.

---

## 5. Validation

```bash
# Timer is scheduled
systemctl list-timers loki-watchdog.timer        # shows NEXT / LAST

# Last run result
journalctl -u loki-watchdog.service -n 40 --no-pager
cat /var/lib/loki-watchdog/heartbeat             # ISO timestamp of last completion
cat /var/lib/loki-watchdog/last_rc               # 0 = all healthy/healed
```

**Controlled failure test** (proves heal actually works — do this once, off-peak):

```bash
docker stop loki-vault-mcp                        # simulate a hang/crash
sudo /usr/local/sbin/loki-watchdog.sh             # force a run
#   Expect: WARN "mcp UNHEALTHY ..." -> "up -d" -> INFO "mcp recovered"
docker ps | grep loki-vault-mcp                   # back up
```

**Webhook test:**
```bash
WEBHOOK_URL='<your-url>' bash -c 'source /usr/local/sbin/loki-watchdog.sh' 2>/dev/null || true
# Simpler: temporarily set a bad HEALTH_URL in the env, run once, confirm an alert lands.
```

---

## 6. Failure scenarios & how to detect them

| Symptom | Likely cause | Where to look |
|---------|-------------|---------------|
| `CRIT ... STILL DOWN after restart+rebuild` | Real outage (bad image, disk full, OOM) | `journalctl -u loki-watchdog`, `docker logs <container>`, `df -h` |
| Webhook silent during a known outage | Whole host down (Layer 1 can't self-alert) | This is exactly what **Layer 2** below catches |
| Repeated "recovered (restart)" every cycle | Flapping — masking a real bug | `*.fails` counters in `/var/lib/loki-watchdog`; investigate root cause |
| Queue-stall alerts but containers healthy | Ollama slow / rate-limited, or large batch | `docker exec loki-postgres psql -U postgres -d loki_vault -c "SELECT status,count(*) FROM note_submissions GROUP BY status;"` |
| Watchdog never runs | Timer not enabled / docker.sock missing | `systemctl status loki-watchdog.timer` |

---

## 7. Rollback

```bash
# Disarm (stops all healing immediately)
sudo systemctl disable --now loki-watchdog.timer

# Full removal
sudo rm /etc/systemd/system/loki-watchdog.{service,timer}
sudo rm /usr/local/sbin/loki-watchdog.sh /etc/loki-watchdog.env
sudo rm -rf /var/lib/loki-watchdog
sudo systemctl daemon-reload
```
Removing the watchdog changes nothing about the stack itself — Docker's
`restart: unless-stopped` policy still handles plain crashes.

---

## 8. Layer 2 — external dead-man's-switch (host-down + Cowork agents)

Layer 1 cannot alert when a host is **completely** down, and cannot see Cowork agents at
all. Layer 2 is a small external check that runs **off** the hosts.

**What it does, every 30 min (offset ~15 min from Layer 1):**
1. `GET` each host's `/health` (Cloud86 `:3141`, Hetzner Klara AI) — alert if unreachable.
2. Read each host's `heartbeat` file freshness (exposed via a tiny read-only endpoint or
   scraped over SSH) — alert if older than ~35 min (watchdog itself died).
3. Verify the Cowork scheduled agents ran (check their last-run state) — alert if stale.

**Two ways to run Layer 2:**

- **Option A — Cowork scheduled task (fastest to stand up).** A scheduled task in this
  app that every 30 min fetches both `/health` endpoints and pings the webhook on
  failure. Limitation: depends on the desktop app/runtime being active; good for
  notification, not a hard SLA.
- **Option B — independent uptime monitor (recommended for production).** A free
  external monitor (e.g. a small Uptime-Kuma instance on a 3rd host, or a hosted pinger)
  hitting both health URLs. Independent of both hosts AND the desktop app. This is the
  only option that survives "my laptop was closed."

**Cowork agents specifically:** there is no "rebuild the agent process" operation — they
are scheduled prompts, not daemons. The actionable equivalents are: (a) alert when a
scheduled run fails/skips, and (b) re-trigger the task. Wire that into whichever Layer 2
option you pick.

---

## 9. Decisions still needed from you

1. **Webhook URL** (Slack/Discord/email-relay) for `WEBHOOK_URL`.
2. **Cloud86 host/IP** and the **Hetzner Klara AI health port + container/service names**
   (the env Host B block has placeholders).
3. **Layer 2 choice** — A (Cowork task, I can create it now once I have #1 and the host
   URLs) or B (independent monitor, I'll give you the Uptime-Kuma compose).
4. Confirmation that **you** (not this session) will run the install — per your
   anti-interference rules I have not SSH'd or touched prod.
