"""Invariant: vapi/router.py fails-open when rustdesk_controller is unavailable.

The lazy try/except import means an ImportError from rustdesk_controller
disables G34 voice endpoints only — it must NOT prevent other Vapi routes
from registering or the module from loading.

Pattern 30 generalisation: when multiple async paths observe the same
lifecycle signal, each must self-report. Here: missing rustdesk_controller
must be observable via a logged warning, not a silent crash.
"""
from __future__ import annotations

import importlib
import logging
import sys
import unittest.mock as mock

from fastapi import APIRouter, FastAPI, Depends

# Exact G34 route paths registered by rustdesk_controller.voice_tools.
# Pinning these prevents the test from passing when only /troubleshoot exists.
_G34_PATHS = frozenset({
    "/start_rustdesk_session",
    "/next_screen_action",
    "/confirm_action",
    "/end_rustdesk_session",
})

# Core Vapi routes that must always register regardless of rustdesk availability.
_CORE_PATHS = frozenset({"/payment_link", "/escalate_to_anthony"})

# Prefix _reload_vapi_router() mounts the router under.
_PREFIX = "/api/v1/vapi"

# Logger name used by vapi/router.py's lazy-import warning block.
_VAPI_ROUTER_LOGGER = "klaravex.vapi.router"


def _flatten_route_paths(routes) -> set[str]:
    """Collect leaf route paths, resolving FastAPI's lazy `_IncludedRouter`
    wrappers (introduced in newer FastAPI: `app.routes` can hold unresolved
    sub-router branches instead of only flat Route/APIRoute objects)."""
    paths: set[str] = set()
    for r in routes:
        if hasattr(r, "effective_candidates"):
            paths |= _flatten_route_paths(r.effective_candidates())
            continue
        path = getattr(r, "path", None)
        if path:
            paths.add(path)
    return paths


def _reload_vapi_router():
    """Force-reload klara.handlers.vapi.router and return an app with it included."""
    for key in list(sys.modules.keys()):
        if "klara.handlers.vapi" in key:
            del sys.modules[key]

    # Re-import the router module
    vapi_router_module = importlib.import_module("klara.handlers.vapi.router")
    
    # Create a FastAPI app and include the vapi_router
    app = FastAPI()
    app.include_router(vapi_router_module.router, prefix="/api/v1/vapi", dependencies=[Depends(lambda: "mock_secret")])
    
    return app


def test_vapi_router_loads_when_rustdesk_unavailable(caplog):
    """Router must import cleanly even when rustdesk_controller raises ImportError.

    Fail-open contract verified here:
    - router is a FastAPI APIRouter instance
    - A WARNING is logged on the klaravex.vapi.router logger
    - Core non-G34 routes are present
    - G34 routes are absent (fail-CLOSED on rustdesk paths only)
    """
    with mock.patch.dict(
        sys.modules,
        {"rustdesk_controller": None, "rustdesk_controller.voice_tools": None},
    ), caplog.at_level(logging.WARNING, logger=_VAPI_ROUTER_LOGGER):
        mod_app = _reload_vapi_router()

    # Router is a real APIRouter — not None, not a fallback stub
    # The module itself needs to be checked against APIRouter
    assert isinstance(mod_app.router, APIRouter), (
        f"router must be a FastAPI APIRouter; got {type(mod_app.router)!r}"
    )

    # Warning was logged — observable, not a silent crash (Pattern 30)
    warning_texts = [
        r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING
    ]
    assert any("rustdesk" in t.lower() for t in warning_texts), (
        f"Expected WARNING mentioning 'rustdesk' on {_VAPI_ROUTER_LOGGER!r}; "
        f"captured log: {caplog.text!r}"
    )

    route_paths = _flatten_route_paths(mod_app.routes)

    # Core routes present
    for p in _CORE_PATHS:
        assert f"{_PREFIX}{p}" in route_paths, (
            f"{p!r} must register even without rustdesk_controller; "
            f"routes: {sorted(route_paths)}"
        )

    # G34 routes absent — fail-closed on rustdesk side only
    for g34 in _G34_PATHS:
        assert f"{_PREFIX}{g34}" not in route_paths, (
            f"G34 route {g34!r} must be absent when rustdesk_controller is "
            f"unavailable; routes: {sorted(route_paths)}"
        )


def test_vapi_router_has_non_rustdesk_routes_when_rustdesk_unavailable():
    """Non-G34 routes (payment_link, escalate, etc.) must all register
    regardless of rustdesk_controller availability."""
    with mock.patch.dict(
        sys.modules,
        {"rustdesk_controller": None, "rustdesk_controller.voice_tools": None},
    ):
        mod_app = _reload_vapi_router()

    route_paths = _flatten_route_paths(mod_app.routes)
    assert "/api/v1/vapi/payment_link" in route_paths, (
        "payment_link route must be registered even without rustdesk_controller; "
        f"routes: {sorted(route_paths)}"
    )
    assert "/api/v1/vapi/escalate_to_anthony" in route_paths, (
        "escalate_to_anthony route must be registered even without rustdesk_controller; "
        f"routes: {sorted(route_paths)}"
    )


def test_vapi_router_rustdesk_routes_present_when_available():
    """When rustdesk_controller IS importable, all four G34 routes must register.

    sys.modules is fully restored by mock.patch.dict after the test so that
    any rustdesk module deletions inside the context do not leak into other tests.
    """
    with mock.patch.dict(sys.modules):
        # Remove cached rustdesk modules so router.py re-imports them fresh
        for key in [k for k in sys.modules if "rustdesk_controller" in k]:
            del sys.modules[key]
        mod_app = _reload_vapi_router()
        route_paths = _flatten_route_paths(mod_app.routes)

    for g34_path in _G34_PATHS:
        assert f"{_PREFIX}{g34_path}" in route_paths, (
            f"G34 route {g34_path!r} must register when rustdesk_controller "
            f"is available; routes: {sorted(route_paths)}"
        )
