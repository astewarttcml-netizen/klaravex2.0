# Loki Subagent Brief — Phase-1 Auto-Documentation Assist
**Implementation brief for a Loki-mode session. NOT executed here.**

**Status:** Spec/brief for review. The host (orchestrator) session does not implement this. Hand to a Loki-mode session via `/do`. Every production step below is gated on Anthony's explicit per-action approval and a mandatory `note_submissions` INSERT before the action.

---

## Objective

Make the agent auto-generate, for every Klaravex case, (a) a customer-ready **session summary** and (b) the internal **note_submissions** record — both as **drafts Anthony reviews**, never auto-sent. This is the lowest-risk, highest-certainty step of the minute-reduction playbook: ~10 min/case removed, zero customer-facing autonomy, no irreversible actions.

## Scope (in / out)

**In scope**
- Generate a structured session summary from case inputs (issue, steps taken, resolution, follow-up).
- Draft the `note_submissions` row for the action (does NOT bypass the logging policy — it *implements* it).
- Surface both to Anthony for review/edit/approve before anything is sent or committed customer-side.

**Out of scope (explicitly)**
- No customer-facing auto-send (email/portal). Draft only.
- No remediation, no device actions, no irreversible operations.
- No new external services. Uses existing Loki backend only.
- No credential injection from the host session (rule 5).

## Where it plugs in (existing infra — verify before coding)

- Loki backend: FastAPI on Hetzner CX22 (shared with itexperts-berlin initially); Klaravex env `/opt/loki/envs/.env.klaravex`; `docker-compose.klaravex.yml`.
- DB: shared Cloud86 Postgres, **`klaravex_` schema prefix**; `note_submissions` table; `agent_id` = `claude-host-session`.
- DB access pattern (per memory): `docker exec loki_db psql` does NOT work — use **asyncpg via the worker** (`docker exec loki_worker python3 ...`). Confirm current table names with a read query first.

## Subagent task sequence (each production step = approval-gated)

1. **Read-only discovery (no approval needed):** confirm `note_submissions` schema + the Klaravex case/session model. Report findings.
2. **Summary generator (code, no prod):** implement a function that takes case fields → returns a structured summary + a proposed `note_submissions` payload (topic slug: `code-edit` for this change; `decision`/`config-change` as appropriate per action). Unit-test locally.
3. **Review surface:** expose the draft to Anthony (portal/queue/console — match existing Loki pattern). Draft is editable; nothing leaves until approved.
4. **Deploy (APPROVAL GATE):** before any `docker compose ... up -d` or env touch on Hetzner — STOP, present exact commands, get Anthony's explicit per-action OK (rule 4). Deploy with `--force-recreate api worker` only (rule: `beat` is not a valid service name).
5. **Validate:** run 2–3 real cases through it; confirm summary quality + that a `note_submissions` row is written per action.

## Mandatory policy compliance

- **Every action the subagent takes writes a `note_submissions` row BEFORE the next action.** If the INSERT fails, stop and surface it (rule 3). The cache-flush caveat from memory applies if touching WP/Code-Snippets-style state — not expected here.
- Log **var names, never values**, if any env wiring is involved (rule 5).
- No "pick up where we left off" — read TASKS.md / this brief to determine scope (rule 2/6).

## Validation criteria (definition of done)

- [ ] Every test case produces an accurate, plain-language summary Anthony approves with ≤30s edit.
- [ ] A correctly-formed `note_submissions` row is written for each action (correct `agent_id`, topic slug, Klaravex schema).
- [ ] Nothing is sent to a customer without explicit approval.
- [ ] Supervised minutes/case measurably drop (logged in the graduation tracker).

## Risks & rollback

| Risk | Detection | Mitigation / Rollback |
|---|---|---|
| Bad summary auto-released | Customer confusion / rework flag | Hard gate: draft-only, human release. Revert = disable the draft surface. |
| Shared-host change breaks itexperts-berlin | itexperts errors post-deploy | Separate compose/env per project; snapshot container state before deploy; `docker compose ... up -d` rollback to prior image. |
| note_submissions INSERT fails silently | Missing rows on audit | Fail-closed: subagent halts on INSERT error and surfaces it. |
| Scope creep into auto-send | A message Anthony didn't approve | Crosses into Phase-2 → out of scope; revert immediately, disclosure must change first. |

---

## Add-on spec: Klara language-matching (task #10)

Build this in the same `/do` pass. Client-facing assistant = **Klara**; backend/infra = **Loki**. Keep that naming consistent everywhere.

**Requirement:** Klara responds in the **site's language** — German on the German-language sites, English on the English-language sites — across business (klaravex.com / klaravex.com) and personal (personal.klaravex.com / personal.klaravex.com).

**Implementation**
1. **Locale param from the site.** Each Klara widget embed passes `locale` on init: `de-DE` for German pages, `en` for English pages. Source it from the page's `<html lang>` / language toggle so it stays correct when the visitor switches.
2. **Pin response language at the backend.** Loki sets Klara's response language from the passed `locale` in the system prompt. Do not rely on language auto-detection as the primary signal.
3. **Honor explicit toggle.** Default = site/page language; if the visitor flips the language switch (e.g., expat on the .de site choosing EN), the new `locale` is passed and Klara follows.
4. **Localize fixed strings.** Greeting, AI-assist disclosure, escalation/handoff messages, and session-summary template all exist in DE + EN and are selected by `locale`.
5. **Fallback only if no locale.** If the embed sends no `locale`, detect from the first user message — but every site embed should send it, so this is a safety net, not the path.

**Validation**
- [ ] German page → Klara greets + responds in German; EN page → English.
- [ ] Toggling language mid-session switches Klara's language.
- [ ] Disclosure + summary strings match the active locale.
- [ ] Same persona/name "Klara" in both languages.

**Note:** this is widget/config + backend prompt work — no irreversible production action — but the Hetzner deploy step still hits the per-action approval gate above.

## Handoff note
This brief is the input to a Loki-mode `/do` session. The orchestrator session will not run SSH, edit production, or inject credentials. Anthony approves each production step individually.
