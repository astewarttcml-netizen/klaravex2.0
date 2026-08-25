# Klaravex handoff — 24 Aug 2026

**Who:** Anthony / Klaravex LLC (Wyoming). US-only. Host session is orchestrator; implement via subagents. Log `note_submissions` before destructive/prod steps.

## Done (this thread)

1. **personal.klaravex.com copy (theme 1.2.0)** — git **main** `1ecae09e`. Remote-only. Klaravex AI does the heavy lifting so $39 is a session, not a house call. Stripped in-person / “real person” / fake 500+/4.9. Output-buffer rewrite for leftover WP phrases. **Not on Cloud86.** Live site still has old claims.
2. **Race public page** — Azure **live**. Image `klaravexcr.azurecr.io/klaravex-api:race-coming-soon-20260823`, revision **`klaravex-api--0000203`** @ 100%. Title: **launching in a few weeks**. Check: https://api.klaravex.com/race
   - Rollback: `klaravex-api--0000202` / `update-1786245961`.
3. **Business theme case studies** — git **main** (merge `802edb4f`): “Engagements I led”, “Built for” not “Trusted by”. **Not on Plesk.**
4. **Launch emails v2** — `drafts/launch-emails-v2-send-ready.md` on main. First person, no location, LinkedIn rec about Anthony not Klaravex. Race P.S. = few weeks. **Do not send** until personal incognito is clean.
5. Local merge of `cursor/race-coming-soon-and-case-studies` → **main** `802edb4f`. Confirm `origin/main` has that merge (push to main was blocked once from Cursor).

## Still production (do these)

### P0 — personal.klaravex.com (Plesk / Cloud86 `45.82.191.203`)

Upload inner theme:

`site-relaunch/2026-06-07-live-deploy/themes/klaravex-personal-theme/klaravex-personal-theme/`

(`KVXP_VERSION` **1.2.0**). Backup live theme → overwrite → **LiteSpeed purge**.

WP Admin:

- Tagline off “Real People”.
- Edit FAQ / pricing / IT Help / scam / TOS bodies.
- Chat plugin: **“Talk to a person” → “Get help now”**.

Incognito grep: no `in-person`, `500+`, `4.9`, Sarah/Raj/Jamie, `Talk to a person`, `human engineer`.

Then send launch emails.

### P0 — klaravex.com case-study PHP

Same Plesk, theme `klaravex-theme`: `front-page.php` + `template-parts/sections/case-studies.php` from `klaravex-theme-src`.

### P1 — WP REST deploy path

LiteSpeed strips `Authorization`. Old jump `loki_auto` / `:443` is dead. Use Plesk File Manager or a working FTP user (1Password: Plesk, WP Personal Admin `7mtre4fc…`, WP Klaravex Admin `utgplhobl…`). Do not paste secrets in chat.

### P1 — Git

Push **main** if origin is still at `1ecae09e`. Do not force-push.

## Do not ship / do not confuse

- Race as “live competing.” Public copy = **few weeks**.
- Fake reviews / 500+/4.9. FTC 16 CFR Part 465.
- Case studies as Klaravex contracts → **engagement I led**.
- `$49/user` to NLSLA (242 seats).
- Privacy “without human review” = **keep** (GDPR automated-decision).
- Growth OS PRD `docs/prd-growth-os.md` + beat-trigger disables + fleet bridge → **Klaravex2.0**, not this tree. Leave unstaged unless Anthony says otherwise. Do not merge `klaravex-os` (Founders OS / client portal) with **KLARAVEX-OS** (`:4100` operator console).
- `/opt/klaravex` is dead. WordPress is **not** Azure.
- Defense / CMMC / ITAR out of scope.

## Azure (works)

CLI: `/home/anthony/tools/azure-cli/bin/az` (not broken `/usr/bin/az`). SP logged in. ACR: **`klaravexcr`**. RG: `klaravex-prod`. App: `klaravex-api`.

Do **not** `az acr build` with context `infra/` (~25 GB). Slim context; skip `.loki`, `docker-services`, rustdesk `target/`, `sd-image-gen`. Dockerfile `COPY`s both `infra/` and `app/` so layout must include both.

## Email send order (after personal is clean)

- Tue: Nick / Mark / Ocean
- Wed: Aspet / Zac
- Thu: Nystrom alone
- Following Tue: Jue / Chris / Guillermo
- Lau after Ocean

Phones: (833) most; (424) Nystrom/Lau. Consumer line: Klaravex AI named in chat; $39 / $29/mo / $39 family.
