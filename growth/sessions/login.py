"""Headed Google SSO login for freelance platforms that have no password form.

Upwork, Guru, and PeoplePerHour all use Continue with Google. One persistent
Chromium profile holds the Google session; each site is then connected in turn.

Usage:
    cd /home/anthony/Klaravex2.0
    .venv/bin/python -m growth.sessions.login --all
    .venv/bin/python -m growth.sessions.login upwork
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from growth.sessions.vault import PLATFORMS, save_cookie, sessions_dir

_GOOGLE_BUTTONS = (
    "Continue with Google",
    "Sign in with Google",
    "Log in with Google",
    "Sign in with google",
)


def _profile_dir() -> Path:
    d = sessions_dir() / "browser-profile"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(sessions_dir(), 0o700)
    return d


def _cookie_header(context, domain_substr: str) -> str:
    pairs: list[str] = []
    needle = domain_substr.lstrip(".")
    for c in context.cookies():
        host = (c.get("domain") or "").lstrip(".")
        if needle not in host:
            continue
        name = c.get("name") or ""
        value = c.get("value") or ""
        if name and value:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _looks_logged_in(platform: str, url: str) -> bool:
    u = url.lower()
    if "accounts.google.com" in u:
        return False
    if platform == "upwork":
        if "account-security/login" in u or "/login" in u.split("upwork.com", 1)[-1]:
            return False
        return any(x in u for x in ("find-work", "/nx/", "/ab/messages", "/freelancers/"))
    if platform == "guru":
        if "login.aspx" in u or "/login" in u:
            return False
        return "guru.com" in u
    if platform == "peopleperhour":
        if "/site/login" in u or "/login" in u:
            return False
        return "peopleperhour.com" in u
    return "login" not in u and "sign-in" not in u


def _dismiss_noise(page) -> None:
    for label in ("Accept", "Accept all", "I agree", "OK", "Got it"):
        btn = page.get_by_role("button", name=label)
        if btn.count():
            try:
                btn.first.click(timeout=1200)
            except Exception:
                pass


def _click_google(page) -> bool:
    for name in _GOOGLE_BUTTONS:
        loc = page.get_by_role("button", name=name)
        if loc.count():
            loc.first.click()
            return True
    loc = page.locator("a:has-text('Google'), button:has-text('Google')")
    if loc.count():
        loc.first.click()
        return True
    return False


def _wait_logged_in(page, platform: str, timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _looks_logged_in(platform, page.url):
            page.wait_for_timeout(2000)
            return True
        page.wait_for_timeout(1000)
    return False


def login_platforms(platforms: list[str], timeout_s: int = 420) -> int:
    unknown = [p for p in platforms if p not in PLATFORMS]
    if unknown:
        print(f"unknown platform(s): {unknown}. allowed={list(PLATFORMS)}", file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright missing. pip install playwright && python -m playwright install chromium",
            file=sys.stderr,
        )
        return 2

    profile = _profile_dir()
    print("Google SSO for:", ", ".join(PLATFORMS[p]["label"] for p in platforms))
    print("A Chromium window will open on this desktop.")
    print("Sign into Google once (including 2FA). The same session is reused for the other sites.")
    print(f"profile={profile}")

    failed: list[str] = []
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile),
            headless=False,
            locale="en-US",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_https_errors=False,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Warm Google in this profile so later Continue-with-Google is one click.
        page.goto("https://accounts.google.com/", wait_until="domcontentloaded", timeout=60000)
        print("Complete Google sign-in in the window if asked (waiting up to 4 minutes)…")
        google_deadline = time.time() + min(timeout_s, 240)
        while time.time() < google_deadline:
            u = page.url.lower()
            if "accounts.google.com" in u and ("signin" in u or "identifier" in u or "challenge" in u):
                page.wait_for_timeout(1000)
                continue
            if "myaccount.google.com" in u or "accounts.google.com/b/" in u or "mail.google.com" in u:
                break
            # Already signed in: Google bounced to account chooser / myaccount / search
            if "accounts.google.com" not in u:
                break
            if "signin" not in u and "identifier" not in u and "challenge" not in u:
                break
            page.wait_for_timeout(1000)
        print(f"google_url={page.url.split('?')[0]}")

        for platform in platforms:
            spec = PLATFORMS[platform]
            print(f"— {spec['label']} {spec['login_url']}")
            page.goto(spec["login_url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            _dismiss_noise(page)

            if _looks_logged_in(platform, page.url):
                print(f"  already logged in")
            else:
                clicked = _click_google(page)
                print(f"  google_button={'clicked' if clicked else 'not found — complete login in the window'}")
                # OAuth may open a popup
                try:
                    popup = page.wait_for_event("popup", timeout=8000)
                    popup.wait_for_load_state("domcontentloaded")
                    print(f"  google_popup={popup.url.split('?')[0]}")
                except Exception:
                    pass
                ok = _wait_logged_in(page, platform, timeout_s=180)
                if not ok:
                    print(f"  still on {page.url.split('?')[0]}")
                    failed.append(platform)
                    continue

            header = _cookie_header(context, spec["cookie_domain"])
            if header.count("=") < 2:
                print("  logged-in URL but too few site cookies")
                failed.append(platform)
                continue
            meta = save_cookie(platform, header, source="playwright_google_sso")
            print(f"  saved {meta['cookie_pairs']} cookies")

        context.close()

    if failed:
        print("not connected:", ", ".join(failed), file=sys.stderr)
        return 1
    print("All requested sessions saved. Refresh Connections → Freelance.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Google SSO capture for freelance sessions")
    p.add_argument("platform", nargs="?", choices=sorted(PLATFORMS))
    p.add_argument("--all", action="store_true", help="Upwork + Guru + PeoplePerHour")
    p.add_argument("--timeout", type=int, default=420)
    args = p.parse_args(argv)
    if args.all:
        platforms = ["upwork", "guru", "peopleperhour"]
    elif args.platform:
        platforms = [args.platform]
    else:
        p.print_help()
        return 2
    return login_platforms(platforms, timeout_s=args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
