# AI Remote Session — Architecture Spec

> **⚠️ HOST STATUS UNCERTAIN POST-MIGRATION (2026-07-10):** Hetzner CX22 (`178.105.84.32`) referenced below is now read-only (tailnet alias `hetzner-cx22`, 100.78.231.58) since the 2026-07-05/06 Azure migration and 2026-07-01/02 rig+USA HA cutover. Verify current RustDesk relay placement against [`../../runbooks/rig-usa-ha-stack-2026-07-01.md`](../../runbooks/rig-usa-ha-stack-2026-07-01.md) (RustDesk not listed in §4 container inventory) before treating `178.105.84.32` as live.

> **DEPLOYMENT UPDATE 2026-06-11:** Transport decision changed — instead of building the
> §1 helper + §2 WebSocket relay + input-injection driver from scratch, we adopt
> **RustDesk self-hosted** (forks all three: capture, mouse/keyboard injection, NAT relay,
> signed client). The RustDesk relay/ID server is **LIVE** on the Hetzner box — see
> `infra/rustdesk-server-DEPLOYED.md`. §3 AI controller is re-pointed to drive the RustDesk
> protocol (receive frame → Claude computer-use → emit input events). §1/§2 below are
> retained for historical rationale; the relay portion is now SUPERSEDED by the live deploy.

**Owner:** Anthony · **Date:** 2026-06-11 · **Status:** v0.1 draft for MVP scoping

Klaravex's core product is an AI that connects to and controls a customer's machine to fix their problem after Klara (Vapi voice agent) triages and charges $79. No off-the-shelf product does this end-to-end (Atera killed the Splashtop SOS API; AnyDesk needs managed devices; ScreenConnect needs a human host). We build it.

This spec covers the eight components that have to exist for v1.

---

## 1. Customer-side helper app

A small native binary the customer downloads after payment. It captures the screen, streams frames to the relay, and executes input events (clicks, keystrokes) sent back from the AI controller.

- **Distribution:** Direct download from `support.klaravex.com/download/<session-token>`. NOT app stores. App store review (Apple notarization queue, Microsoft Store cert) takes days-to-weeks and adds friction for an audience that's already on the phone with us. Direct download is also how every legitimate remote-support tool (TeamViewer QS, Splashtop SOS, Zoho Assist) ships their session-scoped client. The download URL embeds the session token so the binary self-configures with no UI typing.
- **Code-signing:** Required on both OSes or SmartScreen/Gatekeeper will block install for a 60+ year-old caller and the session dies on the spot.
  - Windows: **Sectigo EV Code Signing** ~$300–400/yr, ~3–5 business days issuance, instant SmartScreen reputation. Standard (OV) certs require reputation build-up — too slow for us.
  - macOS: **Apple Developer Program** ($99/yr) + notarization. Built-in, no third party.
  - DigiCert is ~2× Sectigo's price for equivalent EV; pick Sectigo unless Anthony has an existing DigiCert relationship.
- **OS support matrix (v1):** Windows 10/11 x64 first (~70% of the demographic). macOS 13+ (Intel + Apple Silicon) second, target within 60 days of Windows ship. **Linux deprioritized indefinitely** — <2% of consumer support calls, X11/Wayland fragmentation makes input injection unreliable.
- **Permission model:** OS-level prompts at first launch only. Windows: UAC elevation request once for input-injection driver install. macOS: Accessibility + Screen Recording permission prompts (system dialogs, we cannot bypass). Klara explains the prompts verbally before they appear. After grant, no further prompts in-session.
- **Kill-switch UX (three independent paths, all must work):**
  1. Always-visible red **STOP** button in the system tray / menu bar — one click ends the session and revokes the token.
  2. Global hotkey **Ctrl+Shift+X** (Cmd+Shift+X on Mac) — fires even if the AI has focus.
  3. Server-side override — Anthony or the relay can terminate the session remotely; helper enforces within 1 second.
- **Uninstall:** Helper self-deletes on session end by default. Persistent install is opt-in and disabled in v1 (no reason for a one-shot fix tool to linger). Standard OS uninstaller as backup.

**STATUS: DECIDED (2026-06-12, G32)** — §1 helper is **a fork of RustDesk's client** (AGPL-3.0; separation strategy in `docs/decisions/2026-06-12-consumer-ai-remote-transport.md`). Distribution, OS order, kill-switch design, code-signing (Sectigo EV + Apple notarization) and consent + visible-AI-control + recording requirements are inherited from this spec and bolted onto the forked client UI. **OPEN:** Whether to ship the Windows input-injection driver as a kernel driver (more reliable, requires EV cert + WHQL) or user-mode SendInput (simpler, blocked by some games/anti-cheat, but irrelevant for our use case) — RustDesk uses user-mode by default, which is the v1 path unless UAC-dialog control becomes a hard requirement.

---

## 2. Relay server

The middlebox that ferries frames customer→AI and actions AI→customer. Customer's helper opens an outbound connection to the relay (NAT-friendly); AI controller also connects to the relay. Relay never stores frames after a session ends.

- **Transport:** **WebSocket over TLS** for v1. WebRTC would give us ~100ms lower frame latency, but our bottleneck is the vision LLM (2–5s per inference), so the transport savings are noise. WebSocket is simpler to operate (no STUN/TURN, no SDP negotiation), easier to debug, and supported natively in every language we'd use. Revisit WebRTC only if/when the vision model drops below 500ms.
- **Where it runs:** Hetzner CX22 (the existing Loki box) for v1. €4.51/mo, 2 vCPU / 4GB RAM. Move to a dedicated CCX23 or equivalent once concurrent sessions exceed ~10.
- **Scaling:** One process per concurrent session, each process pumping JPEG frames at 1–2 fps + a low-volume action channel. Realistic ceiling on a CX22: **10–20 concurrent sessions** before CPU on JPEG handling saturates. At 100 sessions/month with 20-min average, peak concurrency rarely exceeds 3 — CX22 is comfortable.
- **Security:**
  - Per-session signed tokens (HS256 JWT, 4-hour TTL, single-use, bound to session_id + customer_email).
  - TLS 1.3 everywhere; relay terminates TLS with a Let's Encrypt cert on `relay.klaravex.com`.
  - No persistent customer data on the relay — frames are forwarded in memory and dropped. The dataset capture (§5) is a separate write path to object storage.
  - Relay logs only session metadata (session_id, start/end, byte counts), never frame contents.

**STATUS: DECIDED (2026-06-12, G32)** — §2 relay is **RustDesk self-hosted** (`hbbs` + `hbbr`), **LIVE on Hetzner public edge** `178.105.84.32` (see `infra/rustdesk-server-DEPLOYED.md`). The original WebSocket-over-TLS design is SUPERSEDED — the RustDesk protocol carries §2's role (NAT traversal + frame ferrying + action channel + per-session signed credentials) on the same CX22 the spec originally targeted. Per-session signed tokens are now session IDs issued by `support.klaravex.com` and bound into the helper's pre-configured download. **RESEARCH-NEEDED:** Concrete CX22 frame-throughput benchmark for RustDesk specifically before we promise 20 concurrent sessions. Spin up a 10-session load test before first paid customer.

---

## 3. AI controller

The process that takes a frame + a goal ("fix the customer's WiFi") and produces the next action.

- **Vision model:** **Claude Opus 4.7 multimodal.** Rationale: (a) we already pay Anthropic for Klara, single vendor + single billing relationship; (b) Opus 4.7's safety posture refuses obviously-harmful actions (deleting user files unprompted, etc.) which materially reduces our liability exposure; (c) UI element detection accuracy is competitive with GPT-4o for desktop UIs based on Anthropic's published computer-use benchmarks. GPT-4o vision is the credible alternative if Anthropic latency degrades.
- **Frame rate:** **1–2 fps to the model.** The helper can capture at 10–15 fps for local recording, but we sub-sample to the LLM because inference is 2–5s. Higher rates just waste tokens and money.
- **Action-confirmation gate (mandatory, every action):**
  1. **Predict** — model returns `{action_type, target_description, target_coords, rationale}`.
  2. **Speak** — Klara verbalizes the rationale in plain English ("I'm going to click the WiFi icon in your bottom-right corner — is that okay?").
  3. **Confirm** — customer says yes/no. No action fires without an affirmative.
  4. **Execute** — helper executes the action, captures the next frame, loop.
- **Fallback when vision is wrong:** If the model's confidence is low, or two consecutive actions are rejected by the customer, or the customer says "no that's wrong" — the controller aborts, Klara apologizes, the session is logged with a `fallback_triggered=true` flag, and we offer voice handoff to Anthony (§7). Failed sessions become training data, not lost revenue.

**STATUS: DECIDED** — Claude Opus 4.7, 1–2 fps, confirmation gate. **OPEN:** Confidence threshold for triggering abort. No production data yet. Start at "abort after 2 consecutive customer rejections OR model self-reported confidence <0.6" and tune from logs.

---

## 4. Voice integration

Klara already handles the call. We add four tools she can invoke via the existing `/api/v1/vapi/tool-call` endpoint on api.klaravex.com.

- **New Klara tools:**
  - `start_remote_session(customer_email, problem_summary)` → returns `{session_id, download_url}`. Klara reads the download URL to the customer ("Go to support.klaravex.com slash R-7-K-2…").
  - `next_screen_action(session_id)` → returns `{action_description, awaiting_confirmation: true}`. Klara reads the description verbatim and asks for confirmation.
  - `confirm_action(session_id, confirmed: bool)` → fires or cancels the pending action; returns the next frame's predicted action.
  - `end_remote_session(session_id, outcome: 'fixed' | 'failed' | 'handoff')` → tears down, triggers post-session email + receipt.
- **The loop:** Klara → tool call → AI predicts → tool returns natural-language description → Klara speaks it → customer confirms → tool call confirm → helper executes → frame captured → predict → repeat.
- **Latency budget:** Target **<8s end-to-end per action** (customer says "yes" → action executes → next prompt). Breakdown: confirm round-trip 1s, action execute + frame capture 1s, vision inference 3–5s, Klara TTS 1s. While waiting, Klara fills silence ("One moment while I look at your screen…") — pre-recorded snippets via Vapi to avoid synthesis latency.

**STATUS: DECIDED** — tool shape, loop, latency target. **OPEN:** Whether `confirm_action` should also accept implicit "yes" (silence for 3 seconds) for trivial actions like clicking OK on a dialog. Annoying older customers with constant yes/no may hurt completion rate. Decide after first 20 real sessions.

---

## 5. Dataset capture

Every session is captured for both quality review and future fine-tuning.

- **Schema (per action event, JSONL):** `call_sid`, `customer_email`, `session_id`, `frame_index`, `frame_image_url`, `ai_predicted_action`, `customer_confirmed` (bool), `action_executed` (bool), `action_result` (success/error string), `voice_transcript_segment`, `ts`.
- **Storage:** S3-compatible object store on Hetzner (Hetzner Object Storage or self-hosted MinIO on the CX22). Estimate **~10 MB per session** for the screen recording (1 fps JPEG @ 1080p, 20 min) + ~50 KB JSONL events. 100 sessions/month = ~1 GB/month — trivial.
- **Retention:**
  - Raw frames and audio: **90 days**, then auto-purged. This caps liability exposure and storage cost.
  - Derived data (action sequences, transcripts, outcome labels): **perpetual** — these are what fine-tunes are trained on, and they're scrubbed of frame content.
- **Future fine-tune path:** After ~500 successful sessions, we have enough action-outcome pairs to fine-tune a Klaravex-specific UI-action model (smaller, cheaper, faster than Opus). Vendor TBD — Anthropic's fine-tune API, an open-weights model on Hetzner GPU, or both as A/B.

**STATUS: DECIDED** — schema, storage, retention. **RESEARCH-NEEDED:** GDPR retention review before EU customers. The 90-day raw retention may need to be shorter for EU under "data minimization." Talk to a German DPO/Datenschutzbeauftragter before EU launch.

---

## 6. Audit + liability

Klaravex AI is going to be controlling a stranger's computer. We need a defensible paper trail for every action.

- **Consent flow:** On first helper launch, before any frames are sent, a modal: "I authorize Klaravex AI to view and control this computer for the duration of this support session (session ID: …). I understand I can stop the session at any time using the STOP button or Ctrl+Shift+X." Customer must check a box and click Continue. We record `{session_id, consent_text_version, timestamp, ip_address, customer_email}` to the immutable log. Klara reads the consent text aloud for accessibility before the modal appears.
- **Court-admissible log:** Append-only event log written to S3 with object-lock + SHA-256 hash chaining (each entry includes hash of previous entry). For high-value disputes, batch-anchor daily root hashes to **OpenTimestamps** (free, Bitcoin-blockchain-anchored). This gives us a defensible "this log was not altered after the fact" position without paying a notary.
- **Incident playbook (when the AI does something wrong):**
  1. Kill switch fires (customer or auto-abort).
  2. Session immediately frozen, logs sealed, frames preserved past the 90-day window pending review.
  3. Customer offered full $79 refund via Stripe; refund is one-click for Anthony in admin.
  4. Root-cause analysis recorded against the session for training set inclusion.
  5. If material damage is alleged, E&O insurance (Cowbell, bound 2026-06-10, $1M aggregate) is the backstop. Notify Cowbell within policy window.

**STATUS: DECIDED** — consent flow, log architecture, playbook. **OPEN:** Whether to require customer to verbally re-affirm consent at the start of *each* action category (file deletion, password change, system settings) vs. once per session. More friction, less liability. Default to once-per-session for v1 and revisit after first incident.

---

## 7. Failover to human (Anthony)

When the AI is failing or the customer panics, we need a one-button escape to a real person.

- **Helper UI:** Prominent "**Talk to a person**" button in the helper window, second only to STOP in visual weight. Clicking it:
  1. Ends the AI session (sends `end_remote_session(outcome='handoff')`).
  2. Triggers a Twilio outbound call to Anthony's mobile within 30 seconds.
  3. Leaves the helper running with a "Connecting you to Anthony…" status.
- **Human takes over the same session:** Anthony opens `admin.klaravex.com/sessions/<id>/control` in any browser (admin auth via existing Vapi/admin login). The page renders the live frame stream from the *same helper app, same relay connection, same session_id* — no reinstall, no second download. Anthony's mouse and keyboard events go through the same action channel the AI used. Customer sees no change other than Klara handing off ("I'm connecting you to Anthony now.").
- **Why this matters:** This is also our pressure release valve during the early months when the AI is wrong frequently. Every handoff is a labeled training example for the dataset.

**STATUS: DECIDED** — button placement, Twilio callback, same-session takeover. **OPEN:** Whether the web-based controller needs its own QA before MVP, or if Anthony can use a regular VNC viewer pointed at the relay for v0. Probably v0 is fine — Anthony is the only operator.

---

## 8. Cost model + margin math

Per-session unit economics, assuming 20-minute average fix and 100% session-to-fix success (optimistic):

| Cost line | Estimate |
|---|---|
| Claude Opus 4.7 vision API (~$1.50–2.00/min × 20 min) | **$30–40** |
| Relay CPU + bandwidth (CX22 amortized + egress) | **~$0.10** |
| Code-signing cert amortized ($400/yr ÷ 200 sessions/mo ÷ 12) | **~$0.17** ($0.50 at lower volume) |
| Stripe processing fee (2.9% + $0.30 on $79) | **~$2.59** |
| Twilio inbound voice (Vapi already accounted for in Klara cost) | ~$0.20 |
| **Total COGS** | **~$33–43/session** |

- **Revenue:** $79/session.
- **Gross margin:** ~$36–46/session, **46–58% margin** (slightly tighter than the original 48–61% once Stripe fees are included — easy to miss).
- **Annual @ 100 sessions/mo:** $94,800 revenue / ~$50,000 gross margin.

**STATUS: OPEN** — this assumes 100% session-to-fix rate. In reality, a non-trivial share of sessions will end with refund (AI got stuck, customer rage-quit, problem out of scope). Margin compresses linearly with refund rate. **Decision criterion:** what refund rate is acceptable? At 20% refunds, gross margin drops to ~$29–37/session (~37–47%). At 40%, it's break-even. Track refund rate weekly from session 1; if >25% sustained after first 50 sessions, the unit economics need a price increase or a tighter scope of supported problems before we scale.

---

*End of spec.*
