"""Klaravex dropped-call recovery package.

Public surface:
- recovery.router : FastAPI router mounted at /api/v1/recovery with three
  customer-facing CTA endpoints (resolved / callback / refund).
- recovery.tokens : HMAC-signed token helpers used by both the email
  composer (vapi.dropped_call_recovery) and the router.
"""
