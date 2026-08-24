"""Growth adapters — Layer C external tool boundary."""

from __future__ import annotations

from typing import Any

from growth.adapters.credentials import creds_configured, creds_detail


def not_wired(name: str) -> dict[str, Any]:
    if creds_configured(name):
        return {
            "adapter": name,
            "status": "ready",
            "detail": f"{creds_detail(name)} — live invoke not implemented; wire in adapter module",
        }
    return {
        "adapter": name,
        "status": "stub",
        "detail": creds_detail(name),
    }


def poc_sandbox(name: str, action: str, sample: dict[str, Any] | None = None) -> dict[str, Any]:
    if creds_configured(name):
        detail = f"{creds_detail(name)} — GROWTH_POC_MODE blocks live I/O"
        status = "ready"
    else:
        detail = "GROWTH_POC_MODE=true — live adapter I/O disabled"
        status = "poc_sandbox"
    return {
        "adapter": name,
        "status": status,
        "action": action,
        "detail": detail,
        "sample": sample or {},
        "poc_mode": True,
        "creds_configured": creds_configured(name),
    }
