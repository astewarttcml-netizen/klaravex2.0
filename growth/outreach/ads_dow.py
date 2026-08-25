"""Day-of-week ads toggle — LinkedIn + Meta lack native dayparting on daily budgets.

Usage: python -m growth.outreach.ads_dow --action on|off|preflight
Timers activate campaigns Tuesday morning and pause them Friday morning (ET),
so paid runs Tue/Wed/Thu only. Google is handled natively via ad_schedule.

2026-08-25 hardening (post "No image" incident, $42 wasted spend):
- `--action on` now runs a fail-closed LinkedIn creative preflight: every
  campaign must have >= 1 ACTIVE creative whose underlying post carries an
  image (article thumbnail or media id). Any missing image, API error, or
  unparseable response BLOCKS activation and writes ads-dow-blocked.flag.
- `--action preflight` runs the same check read-only (no status changes).
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from growth.adapters.credentials import _merged_env

LINKEDIN_CAMPAIGNS = ("881380793", "881360493", "881310593")
META_CAMPAIGNS = ("120249910953760238", "120249910953630238")

LINKEDIN_VERSION = "202402"
FLAG_PATH = Path(__file__).resolve().parents[1] / "data" / "ads-dow-blocked.flag"


def _env(key: str) -> str:
    return (_merged_env().get(key) or "").strip()


def _li_token() -> str:
    return _env("LINKEDIN_ADS_ACCESS_TOKEN") or _env("LINKEDIN_ADS_TOKEN")


def _li_get(path: str) -> dict:
    req = urllib.request.Request(
        f"https://api.linkedin.com{path}",
        headers={
            "Authorization": f"Bearer {_li_token()}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": LINKEDIN_VERSION,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_has_image(post: dict) -> bool:
    content = post.get("content") or {}
    article = content.get("article") or {}
    if article.get("thumbnail"):
        return True
    media = content.get("media") or {}
    if media.get("id"):
        return True
    multi = content.get("multiImage") or {}
    if multi.get("images"):
        return True
    return False


def linkedin_preflight(campaign_ids: tuple[str, ...] = LINKEDIN_CAMPAIGNS) -> dict:
    """Fail-closed render check. ok=True only if EVERY campaign has at least
    one ACTIVE creative whose post carries an image. Any error => ok=False."""
    results: list[dict] = []
    ok = True
    for cid in campaign_ids:
        entry: dict = {"campaign": cid, "creatives_checked": 0, "with_image": 0}
        try:
            camp_urn = urllib.parse.quote(f"urn:li:sponsoredCampaign:{cid}", safe="")
            data = _li_get(
                f"/rest/creatives?q=criteria&campaigns=List({camp_urn})"
            )
            active = [c for c in data.get("elements", []) if c.get("intendedStatus") == "ACTIVE"]
            entry["creatives_checked"] = len(active)
            for cr in active:
                share_urn = cr.get("content", {}).get("reference") or ""
                if not share_urn:
                    continue
                try:
                    post = _li_get(f"/rest/posts/{urllib.parse.quote(share_urn, safe='')}")
                except Exception as exc:  # noqa: BLE001
                    entry.setdefault("errors", []).append(f"post {share_urn}: {exc}")
                    continue
                if _post_has_image(post):
                    entry["with_image"] += 1
            entry["ok"] = entry["with_image"] >= 1
        except Exception as exc:  # noqa: BLE001 — any failure blocks activation
            entry["ok"] = False
            entry.setdefault("errors", []).append(str(exc))
        if not entry["ok"]:
            ok = False
        results.append(entry)
    return {"ok": ok, "campaigns": results}


def linkedin_set(status: str) -> list[dict]:
    token = _li_token()
    out = []
    for cid in LINKEDIN_CAMPAIGNS:
        body = json.dumps({"patch": {"$set": {"status": status}}}).encode()
        req = urllib.request.Request(
            f"https://api.linkedin.com/v2/adCampaignsV2/{cid}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Restli-Protocol-Version": "2.0.0",
                "Content-Type": "application/json",
                "X-Restli-Method": "PARTIAL_UPDATE",
                "LinkedIn-Version": LINKEDIN_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                out.append({"platform": "linkedin", "id": cid, "status": status, "http": resp.status})
        except urllib.error.HTTPError as exc:
            out.append({
                "platform": "linkedin",
                "id": cid,
                "error": f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}",
            })
    return out


def meta_set(status: str) -> list[dict]:
    token = _env("META_ADS_ACCESS_TOKEN")
    out = []
    for cid in META_CAMPAIGNS:
        data = urllib.parse.urlencode({"status": status, "access_token": token}).encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/v21.0/{cid}", data=data, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                out.append({"platform": "meta", "id": cid, "status": status, "http": resp.status})
        except urllib.error.HTTPError as exc:
            out.append({
                "platform": "meta",
                "id": cid,
                "error": f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}",
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Toggle LinkedIn + Meta campaigns for the Tue-Thu paid window")
    parser.add_argument("--action", choices=["on", "off", "preflight"], required=True)
    args = parser.parse_args()

    if args.action == "preflight":
        report = linkedin_preflight()
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    if args.action == "on":
        if FLAG_PATH.is_file():
            print(json.dumps([{"error": "ads-dow blocked", "flag": str(FLAG_PATH), "reason": FLAG_PATH.read_text().strip()}], indent=2))
            return 1
        # Fail-closed creative render gate: never activate imageless ads again.
        report = linkedin_preflight()
        if not report["ok"]:
            FLAG_PATH.write_text(
                "blocked (auto): preflight found campaign(s) without an ACTIVE image creative — "
                + json.dumps(report["campaigns"])[:400]
            )
            print(json.dumps([{"error": "preflight failed — activation blocked, flag written", "report": report}], indent=2))
            return 1

    li_status = "ACTIVE" if args.action == "on" else "PAUSED"
    results = linkedin_set(li_status) + meta_set(li_status)
    print(json.dumps(results, indent=2))
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
