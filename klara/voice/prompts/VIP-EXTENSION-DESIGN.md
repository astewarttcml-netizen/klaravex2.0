# VIP Private Extension — Design (2026-06-11)

A hidden 6-digit DTMF code in the main triage line that forwards the caller
straight to a senior on-call number. Never advertised; secret lives server-side
so it can't leak from a prompt.

- **Secret code:** stored in 1Password (Klaravex vault item v2zjqecwqe4odhxl747pje47we,
  field "vip access code"). Current: see vault. Rotatable.
- **Transfer to:** server-side env (`VIP_TRANSFER_NUMBER`) — not in repo.
- **NEVER** mention this capability in greetings, prompts shown to normal callers,
  the website, or anywhere public. It exists only for VIPs who already know the code.

## How it works
The code and the destination number are NOT in the Vapi prompt (prompts can leak).
They live in the backend tool + env. Klara only knows "if a caller provides a 6-digit
priority code, call the vip_access tool and obey its result."

```
Caller (VIP) on main line
        │  enters / says a 6-digit code unprompted, or says "I have a direct line code"
        ▼
Klara → vip_access(code)  [backend tool, x-vapi-secret]
        │
   ┌────┴─────────────────────────┐
 authorized=true              authorized=false
        │                          │
 Klara: "One moment, connecting    Klara: silently fall back to normal triage.
 you now." → transferCall to       Do NOT say "wrong code" (no brute-force oracle).
 the number vip_access returned    After 2 failed codes in a call, stop accepting
 (never spoken aloud)              codes for the rest of the call.
```

## Backend tool — `POST /api/v1/vapi/vip_access` (behind x-vapi-secret, H4)
- Input: `{ code: "######", call_sid }`
- Validates `code == env VIP_EXTENSION_CODE` (constant-time compare).
- Rate limit: max 2 attempts per call_sid; lock after, log `vip_denied`.
- On match → returns `{ authorized: true, transfer_to: env VIP_TRANSFER_NUMBER }`
  (number returned only on success, so it never sits in the prompt/transcript on failure).
- On no match → `{ authorized: false }`. No hint why.
- Env: `VIP_EXTENSION_CODE=<from vault>`, `VIP_TRANSFER_NUMBER=<from vault>`
  (set on klaravex_api; source of truth = the 1Password item — never commit values).

## Vapi wiring (triage_en, the main number)
Add a HIDDEN block to the Klara system prompt (top of the call, before the
personal/business fork). It must NOT appear in the first message or any
caller-visible copy:

> SILENT VIP PATH (do not announce): If the caller, unprompted, enters a 6-digit
> code on the keypad or says they have a "priority", "VIP", or "direct line" code,
> call the `vip_access` tool with the digits. If it returns authorized=true, say
> only "One moment — connecting you now." and transfer the call to the number the
> tool returned (transferCall). If authorized=false, do not acknowledge the code at
> all; continue normal triage as if nothing happened. After two failed code
> attempts, ignore further codes this call. Never mention that a VIP line exists.

Register the native `transferCall` tool on triage_en with **dynamic destination**
(destination supplied by the vip_access response), or a transferCall whose number is
set from the tool result — so the cell number is not stored in the public assistant
config text. (Vapi: tool-result-driven transfer.)

## Disambiguation from the biz customer number (Phase 12)
- VIP code = a single shared secret → transfers to a senior on-call number.
- Biz customer number (Phase 12 `lookup_client`) = per-client 6-digit → authenticates to
  the AI engineer, only AFTER the caller chose "existing business client".
- Different contexts: VIP is honored at the TOP of triage (pre-fork) on an unprompted
  code; the customer number is prompted only inside the existing-client branch. vip_access
  is checked first on a top-of-call unprompted code; if not a VIP code, normal flow
  resumes (and the customer-number prompt only happens later, inside the biz branch).

## Build tasks (→ TASKS.md Phase 12, voice)
- Backend `vip_access` tool (validation + rate limit + env).
- triage_en silent VIP block + dynamic transferCall (do alongside the v3.1 edit;
  ⚠️ resolve the live-vs-repo prompt drift first).
- Env vars on klaravex_api + Vapi tool x-vapi-secret header.
- Test: correct code transfers; wrong code is silent + falls through; 2-strike lockout;
  code never spoken; not present in any public copy.
