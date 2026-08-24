"""Day-of-week ads toggle — LinkedIn + Meta lack native dayparting on daily budgets.

Usage: python -m growth.outreach.ads_dow --action on|off
Timers activate campaigns Tuesday morning and pause them Friday morning (ET),
so paid runs Tue/Wed/Thu only. Google is handled natively via ad_schedule.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request

from growth.adapters.credentials import _merged_env

LINKEDIN_CAMPAIGNS = ("881380793", "881360493", "881310593")
META_CAMPAIGNS = ("120249910953760238", "120249910953630238")


def _env(key: str) -> str:
    return (_merged_env().get(key) or "").strip()


def linkedin_set(status: str) -> list[dict]:
    token = _env("LINKEDIN_ADS_ACCESS_TOKEN") or _env("LINKEDIN_ADS_TOKEN")
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
                "LinkedIn-Version": "202402",
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
    parser.add_argument("--action", choices=["on", "off"], required=True)
    args = parser.parse_args()

    li_status = "ACTIVE" if args.action == "on" else "PAUSED"
    results = linkedin_set(li_status) + meta_set(li_status)
    print(json.dumps(results, indent=2))
    return 1 if any("error" in r for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
