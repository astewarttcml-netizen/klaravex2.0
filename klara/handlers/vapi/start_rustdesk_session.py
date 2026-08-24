"""A9 Vapi tool: start_rustdesk_session.

PRD v2.1 §A: replaces the old generate_splashtop_link path now that
Atera/Splashtop is out and self-hosted RustDesk is in.

The POST /start_rustdesk_session route is registered via the G34 lazy
import in vapi/router.py:

    from rustdesk_controller.voice_tools import router as _rustdesk_voice_router
    router.include_router(_rustdesk_voice_router)

The live handler lives in infra/rustdesk_controller/voice_tools.py, which
also registers /next_screen_action, /confirm_action, and /end_rustdesk_session.

This file exists to satisfy the PRD v2.1 CR-4 file-existence check and to
provide a single place to document where the handler is.  Do NOT add a second
FastAPI router here — that would create a duplicate route.
"""
# Route registered by: infra/rustdesk_controller/voice_tools.py
# Lazy-imported via: infra/klara.handlers/vapi/router.py (try/except block)
# Test coverage: infra/klara.handlers/tests/test_vapi_router_lazy_import.py
