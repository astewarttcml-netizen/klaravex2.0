"""A9 Vapi tool aggregator.

Mounts every per-tool sub-router under a single APIRouter so the Klara AI
backend can include it with one line:

    from infra.klara.handlers.vapi.router import router as vapi_router
    app.include_router(vapi_router, prefix="/api/v1/vapi")

Security — H4
-------------
Every endpoint under /api/v1/vapi/* MUST present the shared secret in the
``x-vapi-secret`` header. Without this, /api/v1/vapi/payment_link mints
real Stripe checkout sessions to attacker-controlled emails, and
/api/v1/vapi/escalate_to_anthony rings Anthony's phone from the open
internet.

Anthony must:
  1. Choose a random 32-char token: `python -c "import secrets; print(secrets.token_urlsafe(24))"`
  2. Set VAPI_SHARED_SECRET=<token> in Azure Container App env.
  3. In the Vapi dashboard → Assistants → (each assistant) → Tools →
     (each tool) → Custom Headers, add:
         Name:  x-vapi-secret
         Value: <token>
  4. For the assistant's server URL itself (Server URL Settings →
     Headers) add the same header — that protects /webhook + /tool-call.

verify_vapi_secret fails CLOSED on missing env var (503) or missing /
mismatched header (401). No public Vapi callback in this codebase is
exempt — the /webhook end-of-call-report path also persists tickets and
must be authenticated.
"""

from fastapi import APIRouter, Depends

from ..lib.vapi_verify import verify_vapi_secret
from .advise_client import router as advise_client_router
from .check_payment_status import router as check_payment_router
from .create_b2b_lead import router as create_b2b_lead_router
from .create_intake_lead import router as create_intake_lead_router
from .escalate_to_anthony import router as escalate_router
from .escalate_to_sam import router as escalate_sam_router
from .generate_splashtop_link import router as splashtop_router
from .log_session_outcome import router as log_session_outcome_router
from .lookup_client import router as lookup_client_router
from .open_ticket import router as open_ticket_router
from .vip_extension_check import router as vip_extension_check_router
from .search_knowledge_vault import router as search_knowledge_vault_router
from .payment_link import router as payment_link_router
from .send_booking_link import router as send_booking_link_router
from .send_support_link import router as send_support_link_router
from .start_troubleshooting import router as troubleshoot_router
from .tool_call import router as tool_call_router
from .vip_access import router as vip_access_router
from .webhook_call_event import router as webhook_router

router = APIRouter(dependencies=[Depends(verify_vapi_secret)])
router.include_router(payment_link_router)
router.include_router(check_payment_router)
router.include_router(troubleshoot_router)
router.include_router(splashtop_router)
# 2026-06-26 — RustDesk remote-support link (replaces Splashtop on consumer
# specialists; support.klaravex.com, caller chooses SMS/email).
router.include_router(send_support_link_router)
router.include_router(escalate_router)
# 2026-08-08 — consumer scam escalation → Sam's Identity Recovery team.
# Emails sam@ai.klaravex.com + opens a Critical Atera [chat-scam] ticket.
# Never pages Anthony (personal surface only).
router.include_router(escalate_sam_router)
router.include_router(log_session_outcome_router)
router.include_router(webhook_router)
router.include_router(tool_call_router)
# Phase 12 — B2B voice squad tools (V2 lookup_client, V3 create_b2b_lead,
# V4 send_booking_link, V5 advise_client).
router.include_router(lookup_client_router)
router.include_router(create_b2b_lead_router)
# Step 0a — new-lead intake from triage prompt (consumer/B2B shopping callers).
router.include_router(create_intake_lead_router)
router.include_router(send_booking_link_router)
router.include_router(advise_client_router)
# Phase 12 V6 — open_ticket voice tool (biz_engineer + pillar voices file
# a ticket mid-call: advice_note / work_request / callback / security_note /
# unauthenticated_callback). Writes to klaravex_tickets.
router.include_router(open_ticket_router)
# Phase 12 V12 — VIP silent-transfer gate (vip_access endpoint).
router.include_router(vip_access_router)
# 2026-06-26 — VIP extension secret-code check (Klara-only, never advertised).
router.include_router(vip_extension_check_router)
# 2026-07-26 — Vault search: lets the voice assistant query the Klaravex
# observation vault (note_submissions) for decisions, changes, and notes.
router.include_router(search_knowledge_vault_router)
# G34 — RustDesk AI remote session voice tools: start/next_action/confirm/end.
# Lazy import so a missing controller binary or its Python deps fails-open
# (G34 routes disabled) rather than fail-closed (all Vapi routes down).
try:
    from rustdesk_controller.voice_tools import router as _rustdesk_voice_router
    router.include_router(_rustdesk_voice_router)
except ImportError as _e:
    import logging as _logging
    _logging.getLogger("klaravex.vapi.router").warning(
        "rustdesk_controller unavailable — G34 voice endpoints disabled: %s", _e
    )
