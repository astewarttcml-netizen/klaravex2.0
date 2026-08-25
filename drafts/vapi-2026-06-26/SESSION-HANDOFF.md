# Klaravex Voice — Session Handoff (2026-06-26)

Pick this up in a session that runs on Anthony's machine (Claude Code / terminal)
where `VAPI_API_KEY` + `VAPI_SHARED_SECRET` (1Password Klaravex vault) and network
to `api.vapi.ai` exist. The Cowork session that produced this had no API route, so
**nothing below is deployed except the website price.**

## 1. Deploy status (what is / isn't live)

| Item | State |
|---|---|
| personal.klaravex.com one-time session price $75 → **$79** | ✅ LIVE (WP Customizer, published) |
| Stray blank `handoff_to_assistant` on Triage node (squad 9795422a) | ⚠️ LEFTOVER — delete it in the squad builder |
| 4 pillar engineer assistants | ❌ not created |
| Klara + 6 consumer specialist prompt rewrites | ❌ drafted, not pushed |
| `send_support_link` backend | ❌ in repo, not deployed |
| 6–8 digit codes / `from_number_e164` injection | ❌ in repo, not deployed |
| biz_intake / biz_engineer squad handoffs (dead-air fix) | ❌ not wired |
| **Dead-air bug (business transfer)** | ❌ STILL LIVE |

## 2. Root cause of the dead-air bug (confirmed live, 2026-06-26)

Klara/Triage has handoff tools to the 6 consumer specialists but **none to Biz
Intake or Biz Engineer**. Biz Intake *is* already a squad member, so the runbook's
"add them to the squad" was the wrong fix — the missing piece is the **handoff
tools on Triage**. Transfer model = squad membership + native `transfer_to_specialist`;
do NOT add `transferCall` tools (that broke name resolution before).

## 3. Locked design decisions

- **Klara stays on the call the entire time** — personal: until payment clears;
  business: until transfer to engineer / intake / VIP.
- **Personal:** intake → quote "**seventy-nine dollars**" (never "$79" — TTS) →
  wait for `paid:true` → intent-route to one of 6 specialists → specialist offers
  the RustDesk link (support.klaravex.com) by **SMS / email / go-to-site**. No
  Splashtop. Live Troubleshoot = catch-all.
- **Scam / elder abuse → Identity Recovery (Sam) only**, no paywall, never bridged
  to the founder. System scales Sam horizontally.
- **VIP** = business code path only → "**Transferring you now to a live person.**"
  (no name) → `escalate_to_anthony(bridge_call=true)`.
- **Business:** silent phone lookup → engineer; else **6–8 digit code (# to submit)**;
  "no" → intake; code → client match→engineer / VIP→bridge / neither→one retry→intake.
- **4 website pillars** (klaravex.com/business/services — "Four pillars, fourteen
  services"): Network & Security · Cloud & Productivity · Strategy & Transformation
  (vCISO) · Infrastructure & Support.
- **Business routing = BOTH**: Klara and Biz Engineer can both route to the 4 pillar
  engineers. **Biz Engineer is KEPT** (handles the free assessment + routing).
- **Auth once, carried via rolling history** — pillar specialists don't re-ask for
  the code.

## 4. Files produced (all in repo)

Prompts — `drafts/vapi-2026-06-26/`:
- `triage-en.NEXT.md` (Klara: personal+business, scam→Sam, VIP code, $79→words)
- `windows-expert.NEXT.md`, `apple-expert.NEXT.md`, `mobile-expert.NEXT.md`,
  `smart-home-network.NEXT.md` (RustDesk + scam→Sam)
- `biz-engineer-network-security.NEXT.md`, `biz-engineer-cloud-productivity.NEXT.md`,
  `biz-engineer-strategy-transformation.NEXT.md`,
  `biz-engineer-infrastructure-support.NEXT.md` (the 4 NEW pillar engineers)
- Identity Recovery: unchanged. Live Troubleshoot: no repo prompt (edit in Vapi).

Backend — `infra/loki_handlers/vapi/`:
- `send_support_link.py` (NEW) + mounted in `router.py` + dispatched in `tool_call.py`
- `lookup_client.py` + `vip_extension_check.py` → 6–8 digit codes
- `tool_call.py` → `from_number_e164` envelope injection
- (all `py_compile` clean)

Scripts — `infra/scripts/`:
- `create-pillar-engineers-2026-06-26.py` — clones Biz Engineer → 4 pillar
  assistants, adds to squad, wires handoffs (Klara→{intake,engineer,4 pillars};
  Engineer→4 pillars). Dry-run default.
- `deploy-voice-2026-06-26.py` — prompt pushes, send_support_link tool swap,
  biz_intake/biz_engineer server+tools, squad membership. Dry-run default.

## 5. Run order (from Anthony's machine)

```
# 0. (manual) delete the stray blank handoff_to_assistant on the Triage node.

# 1. deploy backend (send_support_link, 6-8 codes, from_number_e164) to api.klaravex.com
#    — these are prod-only; not staging-isolatable.

# 2. create + wire the 4 pillar engineers
VAPI_API_KEY=… python3 infra/scripts/create-pillar-engineers-2026-06-26.py            # review
VAPI_API_KEY=… python3 infra/scripts/create-pillar-engineers-2026-06-26.py --apply

# 3. prompts + tool swap + biz wiring (also adds Klara→Biz handoffs / dead-air fix)
VAPI_API_KEY=… VAPI_SHARED_SECRET=… python3 infra/scripts/deploy-voice-2026-06-26.py --env prod
…--env prod --apply

# 4. update Biz Engineer prompt: Step 2 switches from advise_client internal routing
#    to transfer_to_specialist → the 4 pillar engineers (keep auth + assessment).
#    (Prompt edit not yet drafted — do in the new session.)

# 5. add advise_client pillar enum value "infrastructure_support" (backend).
```

## 6. Open items / caveats (verify before --apply)

- **`assistantDestinations` schema** in `create-pillar-engineers` is reconstructed
  from the runbook, not verified against the live tenant — run `--dry-run` and
  check the printed member/destination shape first.
- **Biz Engineer prompt** (transfer-route version) is NOT yet written — only the
  current advise_client version exists. Draft it next.
- **advise_client pillar mismatch:** website has 4 pillars; advise_client enum has
  5 different ones (managed_security, microsoft_365, regulatory_readiness,
  ai_adoption, strategic_advisory). Pillar drafts map to the closest; add an
  `infrastructure_support` pillar for clean mapping.
- **No staging mirrors** for biz_intake/biz_engineer; business fork is prod-only to test.
- Original synced prompt `.md` files were NOT modified — all changes are `*.NEXT.md`
  drafts. Pushing them via the script is what makes them live.
