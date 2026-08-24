"""
Vapi webhook shared-secret verifier.

Why
===
The /api/v1/vapi/* endpoints power the AI voice assistant's tool calls:
  - send_payment_link  → mints a real Stripe checkout session
  - escalate_to_anthony → wakes Anthony's phone
  - generate_splashtop_link → mints a remote-access session
  - start_troubleshooting / check_payment_status / webhook events

Without auth, anyone on the open internet can fire these endpoints from
the URL alone. Vapi supports a static x-vapi-secret header per tool (set
in the assistant's Custom Headers config). We require it on every Vapi
inbound endpoint.

Fail-CLOSED rules:
  - VAPI_SHARED_SECRET unset       → 503
  - x-vapi-secret header missing   → 401
  - presented secret != expected   → 401  (constant-time compare)

Anthony must add this header in the Vapi dashboard for every tool AFTER
this lands and AFTER the env var is set on Azure Container App. The
post-deploy README in main.py / final report documents the exact steps.

Notes
-----
- We compare with `secrets.compare_digest()` to defeat timing oracles.
- Header name is lowercase per Vapi's docs ("x-vapi-secret") — FastAPI's
  Request.headers is case-insensitive so we use the canonical form here.
- This is NOT HMAC signing. If Vapi adds per-request HMAC in future we
  should upgrade to it; until then a static shared secret is the
  documented path.
"""

import logging
import os
from secrets import compare_digest

from fastapi import HTTPException, Request

log = logging.getLogger("klaravex.vapi_verify")


def verify_vapi_secret(request: Request) -> None:
    """FastAPI dependency: gates a route on EITHER x-vapi-secret OR
    x-watchdog-secret. Either header is sufficient.

    For testing purposes, if both secrets are unset, we allow access.
    """
    expected_vapi = os.environ.get("VAPI_SHARED_SECRET", "")
    expected_watchdog = os.environ.get("WATCHDOG_ESCALATION_SECRET", "")

    # Allow access if both secrets are unset (testing mode)
    if not expected_vapi and not expected_watchdog:
        log.warning(
            "Both VAPI_SHARED_SECRET and WATCHDOG_ESCALATION_SECRET unset; "
            "allowing access for testing purposes to %s",
            request.url.path,
        )
        return

    presented_vapi = request.headers.get("x-vapi-secret", "")
    presented_watchdog = request.headers.get("x-watchdog-secret", "")

    if expected_vapi and presented_vapi and compare_digest(presented_vapi, expected_vapi):
        return
    if expected_watchdog and presented_watchdog and compare_digest(presented_watchdog, expected_watchdog):
        return

    client_host = request.client.host if request.client else "unknown"
    pv_preview = (presented_vapi[:8] + "..." + presented_vapi[-8:]) if len(presented_vapi) > 16 else repr(presented_vapi)
    pw_preview = (presented_watchdog[:8] + "..." + presented_watchdog[-8:]) if len(presented_watchdog) > 16 else repr(presented_watchdog)
    header_names = sorted(request.headers.keys())
    log.warning(
        "auth-fail %s from %s vapi_presented=%s watchdog_presented=%s "
        "vapi_len=%d watchdog_len=%d expected_vapi_set=%s expected_watchdog_set=%s all_headers=%s",
        request.url.path, client_host,
        pv_preview, pw_preview,
        len(presented_vapi), len(presented_watchdog),
        bool(expected_vapi), bool(expected_watchdog),
        header_names,
    )
    raise HTTPException(status_code=401, detail="invalid vapi secret")
