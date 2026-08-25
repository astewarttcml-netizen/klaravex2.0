# Phase-1 Minute-Reduction Playbook
**Cut supervised time per case without crossing into unsupervised autonomy**

**Status:** Operating playbook — draft for review. No production changes.
**Goal:** Move effective automation from ~10% → ~40% per case while you still approve **every** customer-facing output, so margin improves *before* full graduation and the website stays on Phase-1 disclosure.

---

## Why this is the fastest margin win

In the pricing model, Phase-1 margin is dominated by **your minutes per case** at $2.50/min. You don't need agents to act unsupervised to cut that — you need them to do the *labor* while you keep the *judgment*. Removing ~35 minutes of grunt work from a 60-minute case is a ~40% effective automation gain with **zero** autonomy risk, because nothing reaches the customer without your approval.

**The principle: AI-drafted, human-approved.** The agent produces; you decide and release. This is still "human-delivered" for disclosure purposes — Phase-1 language stays valid.

---

## Where the minutes hide — attack these stages

| Case stage | Today (you do it) | Agent-assisted (you approve) | Min saved (60-min case) | Autonomy risk |
|---|---|---|---|---|
| Intake / triage | You ask questions, classify, gather logs | Agent runs intake chat, classifies category, pulls system info, proposes diagnosis *before* you engage | ~10 | None — you still confirm |
| Drafting the fix | You write steps / response | Agent drafts the fix steps and the customer message; you edit + send | ~10 | None — you send it |
| Reversible execution | You run each step | Agent stages reversible steps; you one-click approve each | ~5–10 | Low — gated on approve |
| Documentation | You write the summary | Agent auto-generates the session summary + incident note | ~10 | **Zero** — internal, post-hoc |
| Follow-up | You write follow-up email | Agent drafts follow-up; you approve | ~5 | None |

**Net: ~35–45 minutes removed from a 60-minute case, with you still approving everything.**

Start with **Documentation** — it's pure time saved at zero risk and requires no trust in the agent's customer judgment. Capture that win day one.

---

## Implementation order (lowest risk → highest)

1. **Auto-documentation (week 1).** Agent writes every session summary + the note_submissions entry. You review for 30 seconds. Zero customer exposure.
2. **Intake/triage (week 2).** Agent handles first contact, classifies, gathers context, hands you a pre-diagnosed case. You take over for the fix.
3. **Response drafting (week 3).** Agent drafts all customer-facing text; you edit and send. Nothing auto-sends.
4. **Reversible execution with approve-gates (week 4+).** Agent proposes/stages reversible actions (password reset, cache clear, driver reinstall); you click approve. **Never** auto-execute anything irreversible or in a Red category.

---

## Guardrails (do not skip)

- **Nothing reaches the customer without your explicit release.** That's the line that keeps this Phase-1.
- **No irreversible action is agent-staged** (backups, deletions, payments, security config) — those stay fully manual until/unless graduated.
- **Log the assist level per case** in the tracker (the "Handled By" field = "Agent (supervised)"). This is also your evidence base for later graduation.
- **Review discipline is the failure mode.** The risk isn't the agent acting alone — it's you rubber-stamping a bad draft because it looks plausible. Read every technical step before release; verify commands.

---

## Measure it

- Add a **"supervised minutes"** value to each logged case (extend the tracker's Notes or a new column).
- Target curve: **Week 1 ≈ 55 min/case → Week 4 ≈ 35 min/case.**
- In the pricing model, raise the **Phase-1 automation %** input from 10% toward 40% as you hit the target and watch Phase-1 margins climb — this is the number you're moving.

## Failure scenarios & detection

| Failure | Detection | Response |
|---|---|---|
| Agent draft is subtly wrong, you release it | Customer reports issue / rework flag in tracker | Tighten review checklist; mark category not-ready |
| Time savings don't materialize | Supervised-minutes metric flat | Identify which stage you're still doing manually; the agent isn't actually drafting it |
| Quiet drift into auto-send | A customer-facing message you didn't approve | Hard stop — this crosses into Phase-2; disclosure must change or the behavior reverts |

## What this is NOT
This keeps you human-in-the-loop. It is **not** graduation to autonomy (that's the tracker's job) and it does **not** trigger Phase-2 disclosure — precisely because you approve every output.
