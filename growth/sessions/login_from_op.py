"""Log into a freelance platform using 1Password, then store the session cookie.

Never prints secrets. Resolves the OP_SERVICE_ACCOUNT_TOKEN from klaravex-os
``.env.local`` when the process env is empty.

Usage:
    cd /home/anthony/Klaravex2.0
    .venv/bin/python -m growth.sessions.login_from_op upwork
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from growth.sessions.vault import PLATFORMS, save_cookie

_OP_ENV_FILE = Path("/home/anthony/klaravex-os/.env.local")

# Service-account-visible Login items that actually have username+password.
_OP_ITEMS: dict[str, tuple[str, str]] = {
    "upwork": ("ck7jkkovjjydfjteyhpt2mskxu", "Klaravex"),
}


def _ensure_op_token() -> None:
    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN"):
        return
    if not _OP_ENV_FILE.is_file():
        return
    for line in _OP_ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("OP_SERVICE_ACCOUNT_TOKEN="):
            os.environ["OP_SERVICE_ACCOUNT_TOKEN"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def _op_creds(platform: str) -> tuple[str, str]:
    if platform not in _OP_ITEMS:
        raise SystemExit(
            f"no 1Password login mapped for {platform}. "
            f"Klaravex/Claude vaults have: {sorted(_OP_ITEMS)}"
        )
    item_id, vault = _OP_ITEMS[platform]
    r = subprocess.run(
        ["op", "item", "get", item_id, "--vault", vault, "--reveal", "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"op item get failed ({r.returncode}): {(r.stderr or '')[:200]}")
    it = json.loads(r.stdout)
    fields = { (f.get("label") or f.get("id") or ""): (f.get("value") or "") for f in it.get("fields") or [] }
    user = (fields.get("username") or fields.get("email") or "").strip()
    password = (fields.get("password") or "").strip()
    if not user or not password:
        raise SystemExit(f"1Password item for {platform} is missing username or password")
    print(f"1Password: {platform} username_len={len(user)} password_len={len(password)}")
    return user, password


def _cookie_header(context) -> str:
    pairs: list[str] = []
    for c in context.cookies():
        name = c.get("name") or ""
        value = c.get("value") or ""
        if name and value:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _looks_logged_in(url: str) -> bool:
    u = url.lower()
    if any(x in u for x in ("login", "sign-in", "signin", "account-security/login")):
        return False
    return any(x in u for x in ("find-work", "nx/", "/ab/messages", "dashboard", "/pro/", "freelancer"))


def login(platform: str, timeout_s: int = 240, headed: bool = True) -> int:
    if platform not in PLATFORMS:
        print(f"unknown platform: {platform}", file=sys.stderr)
        return 2
    spec = PLATFORMS[platform]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright missing. pip install playwright && python -m playwright install chromium", file=sys.stderr)
        return 2

    _ensure_op_token()
    user, password = _op_creds(platform)

    print(f"Opening {spec['label']} login (headed={headed})")
    print(f"URL: {spec['login_url']}")
    print("If 2FA / captcha appears, complete it in the window.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.goto(spec["login_url"], wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        # Cookie banner can intercept clicks.
        for label in ("Accept", "I agree", "OK"):
            btn = page.get_by_role("button", name=label)
            if btn.count():
                try:
                    btn.first.click(timeout=1500)
                except Exception:
                    pass
        # Close the tracking toast if present.
        closer = page.locator("button[aria-label='Close'], button:has-text('×')").first
        if closer.count():
            try:
                closer.click(timeout=1500)
            except Exception:
                pass

        # Upwork: username → Continue → password (or Google SSO)
        user_box = page.locator("#login_username, input[name='login[username]'], input[type='email'], input[name='username']").first
        if user_box.count():
            try:
                user_box.wait_for(timeout=8000)
                user_box.fill(user)
                cont = page.get_by_role("button", name="Continue")
                if cont.count():
                    cont.first.click()
                else:
                    page.keyboard.press("Enter")
                page.wait_for_timeout(1500)
            except Exception:
                pass

        alt = page.get_by_text("Log in a different way")
        if alt.count():
            print("upwork offered Google SSO; trying password via 'Log in a different way'")
            alt.first.click()
            page.wait_for_timeout(2000)

        pwd_box = page.locator("#login_password, input[name='login[password]'], input[type='password']").first
        if pwd_box.count():
            for name in ("Password", "Use password", "Log in with password"):
                method = page.get_by_role("button", name=name)
                if method.count():
                    try:
                        method.first.click(timeout=2000)
                    except Exception:
                        pass
            page.wait_for_timeout(800)
            try:
                pwd_box.wait_for(state="visible", timeout=8000)
            except Exception:
                pass
            pwd_box.fill(password, force=True)
            print("password filled")
            submit = page.get_by_role("button", name="Log in")
            if not submit.count():
                submit = page.get_by_role("button", name="Sign in")
            if not submit.count():
                submit = page.get_by_role("button", name="Continue")
            print(f"submit_buttons={submit.count()}")
            if submit.count():
                submit.last.click()
            else:
                page.keyboard.press("Enter")
        elif page.get_by_role("button", name="Continue with Google").count():
            print("password field absent — clicking Continue with Google (complete 2FA in the window if asked)")
            page.get_by_role("button", name="Continue with Google").first.click()
        else:
            shot = Path("/tmp/upwork-login-debug.png")
            page.screenshot(path=str(shot), full_page=True)
            print(f"no password or Google button url={page.url.split('?')[0]}")
            print(f"title={page.title()!r} screenshot={shot}")
            print("body=", page.inner_text("body")[:800].replace("\n", " | "))
            browser.close()
            return 1

        deadline = time.time() + timeout_s
        captured = ""
        last_url = ""
        while time.time() < deadline:
            last_url = page.url
            if _looks_logged_in(last_url):
                page.wait_for_timeout(2500)
                captured = _cookie_header(context)
                if captured.count("=") >= 2:
                    break
            page.wait_for_timeout(1000)

        print(f"final_url={last_url.split('?')[0]}")
        if not captured:
            captured = _cookie_header(context)
            shot = Path("/tmp/upwork-login-debug.png")
            try:
                page.screenshot(path=str(shot), full_page=True)
                print(f"not_logged_in cookie_pairs={captured.count(';')+1 if captured else 0} screenshot={shot}")
                print("title=", page.title())
                print("body=", page.inner_text("body")[:900].replace("\n", " | "))
            except Exception as exc:
                print(f"not_logged_in screenshot_failed {type(exc).__name__}")
            browser.close()
            return 1

        meta = save_cookie(platform, captured, source="playwright_1password")
        browser.close()
        print(
            f"saved {spec['label']} session "
            f"({meta['cookie_pairs']} cookies, source={meta['source']})"
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="1Password → freelance session cookie")
    p.add_argument("platform", choices=sorted(PLATFORMS))
    p.add_argument("--timeout", type=int, default=240)
    p.add_argument("--headless", action="store_true")
    args = p.parse_args(argv)
    return login(args.platform, timeout_s=args.timeout, headed=not args.headless)


if __name__ == "__main__":
    raise SystemExit(main())
