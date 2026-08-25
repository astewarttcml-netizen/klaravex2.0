# Klaravex Voice — Deploy Manifest (2026-06-26)

Everything in this change set, in execution order. Run from an environment that
has `VAPI_API_KEY` + `VAPI_SHARED_SECRET` set and network to `api.vapi.ai` and
`api.klaravex.com`. **Staging first** on +1-323-760-9918, then prod
+1-424-348-6010. The Cowork session that authored this had no network/keys, so
nothing here has been pushed.

Decisions locked this session:
- Transfer mechanism = **squad membership + existing `transfer_to_specialist`**. Do NOT add `transferCall` tools (broke name resolution before).
- Scam / elder-abuse → **Identity Recovery (Sam) only** (system scales Sam horizontally). Never bridge a personal caller to the founder.
- VIP-to-founder bridge exists **only** on the business code path; spoken line is exactly **"Transferring you now to a live person."** (no name).
- Personal branch: payment clears → intent-route to specialist → specialist offers RustDesk link by **SMS / email / go-to-site** (support.klaravex.com). No Splashtop.
- Business branch: silent phone lookup → engineer; else **6–8 digit code (# to submit)**; "no" → intake; code → client→engineer / VIP→bridge / neither→one retry→intake.
- Price spoken as **"seventy-nine dollars"** (TTS mangles "$79").

---

## A. Backend code (in repo — deploy to api.klaravex.com backend)

### A1. DONE — `send_support_link` (RustDesk link, replaces Splashtop)
- NEW `infra/loki_handlers/vapi/send_support_link.py` (honors delivery=sms|email|both; SUPPORT_URL=support.klaravex.com).
- Mounted in `infra/loki_handlers/vapi/router.py`.
- Dispatch case added in `infra/loki_handlers/vapi/tool_call.py`.
- `py_compile` clean. New env (optional): `SUPPORT_URL`, `SUPPORT_FROM_EMAIL`.

### A2. TODO — Phone-injection for silent lookup + VIP (needs your env to test)
Root cause: Vapi doesn't substitute `{{call.customer.number}}` into tool args.
- `tool_call.py` already injects the real phone into `caller_phone` from the envelope, but **not** into `from_number_e164` (the field `vip_access.py` reads), and the VIP/lookup tools use **dedicated endpoints** that bypass `/tool-call`.
- Fix (two parts):
  1. In `tool_call.py`, after the `caller_phone` injection, also map `real_phone → args["from_number_e164"]` when it's a placeholder.
  2. In the dedicated endpoints (`vip_access.py`, `vip_extension_check.py`, and `lookup_client.py` silent path), parse the raw request envelope and prefer `message.call.customer.number` over the LLM-supplied model field.
- Verify against a real staging call (the synthetic harness won't catch this).

### A3. TODO — 6–8 digit codes (was fixed 6)
- Relax code-length validation in `lookup_client.py` and `vip_extension_check.py` to accept 6–8 digits.
- DTMF: configure the keypad capture to submit on `#` (variable length).

---

## B. Vapi prompt pushes (staging → prod via promote-vapi-change.py)

Each is a `model.messages[0].content` replace with the matching `*.NEXT.md`:

| Target | Draft file | Change |
|---|---|---|
| `klara` (triage_en) | `triage-en.NEXT.md` | personal+business rewrite, scam→Sam, VIP code path, $79→words |
| `windows_expert` | `windows-expert.NEXT.md` | RustDesk, scam→Sam |
| `apple_expert` | `apple-expert.NEXT.md` | RustDesk, scam→Sam |
| `mobile_expert` | `mobile-expert.NEXT.md` | RustDesk, scam→Sam |
| `smart_home_network` | `smart-home-network.NEXT.md` | scam→Sam (voice-only, no RustDesk) |
| `identity_recovery` | — | NO CHANGE (it is Sam) |
| `live_troubleshoot` | — | No repo prompt; if it names Splashtop in Vapi, edit in dashboard |

Command pattern:
`VAPI_API_KEY=… VAPI_SHARED_SECRET=… python3 infra/scripts/promote-vapi-change.py --target <t> --patch '{"path":"model.messages[0].content","value":"<full NEXT.md text>"}'`

---

## C. Vapi tool/assistant config (API or dashboard)

### C1. Consumer specialists (6) — swap Splashtop → send_support_link
- Add `send_support_link` tool schema (params: delivery sms|email|both, caller_phone, caller_email, caller_first_name) with server.url `/api/v1/vapi/send_support_link` (or unified `/tool-call`) + `x-vapi-secret` header.
- Retire `generate_splashtop_link` from these assistants' tool arrays. **Handler file stays** (never-delete) — just unbind the tool.

### C2. biz_intake (b3b0eaf3-6c4d-4d9c-89a3-9b01b785429a)
- server.url = `https://api.klaravex.com/api/v1/vapi/webhook` + `x-vapi-secret`.
- Add FUNCTION tools: `create_b2b_lead`, `send_booking_link`, `escalate_to_anthony`. **No transferCall tool.**

### C3. biz_engineer (f004245a-3ea5-413a-ae30-4c9a7515686c)
- server.url + `x-vapi-secret`.
- Add tools: `lookup_client`, `advise_client`, `escalate_to_anthony`.

### C4. Squad 9795422a — THE DEAD-AIR FIX
- ADD members `biz_intake` + `biz_engineer` so `transfer_to_specialist("Klaravex Biz Intake"/"Biz Engineer")` resolves.
- ⚠️ `promote-vapi-change.py` cannot patch squads — use the Vapi squad API (`PATCH /squad/{id}`) or the dashboard.

### C5. Phone routing
- Confirm `+14243486010` (6334ed60-…) resolves via the squad (triage entry). If the assistantId-only path is taken, clear `assistantId`.

---

## D. Staging caveats (read before staging)
- No `[STG]` mirrors exist for biz_intake / biz_engineer, and the staging squad is consumer-only → the **business fork can't be staged** until you clone them into staging + add to the staging squad, OR accept prod-only for the business side.
- Staging assistants hit the **production backend** (api.klaravex.com) → backend changes (A1–A3) are **not** staging-isolatable; deploy them as additive, low-risk prod changes and test live.

---

## E. Acceptance tests
1. **Personal:** call from a non-VIP number → "personal" → questions → quote says "seventy-nine dollars" → payment clears → routes to the correct specialist by issue → specialist offers SMS/email/site for support.klaravex.com.
2. **Personal scam:** mention an active scam → no paywall, transfers to Identity Recovery (Sam), never to the founder.
3. **Business existing (phone):** call from a client's number → "Welcome back, {company}" → Biz Engineer.
4. **Business existing (code):** "business" → enter valid 6–8 digit code + # → "Welcome back, {company}" → Biz Engineer.
5. **Business new:** "business" → "no" → Biz Intake (transfer FIRES — no dead air).
6. **VIP:** enter VIP extension code → "Transferring you now to a live person." → bridge to founder cell.
7. **Bad code:** wrong code → one retry → still wrong → Biz Intake.

---

## F. Not deleted (never-delete compliance)
- `generate_splashtop_link.py` handler retained; only unbound from assistants.
- Original synced prompt `.md` files untouched; all changes live in `*.NEXT.md` drafts.
- WordPress: personal-site one-time session price changed $75→$79 (live, via Customizer) + theme source defaults updated; business site untouched.
