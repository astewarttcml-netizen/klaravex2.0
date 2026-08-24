"""Harvest live question threads from Reddit for the forums agent.

Reddit blocks anonymous JSON (403) but still serves RSS/Atom feeds. This
pulls each priority subreddit's /new/.rss, filters to fresh question-shaped
threads, and writes a brief with real permalinks so replies target actual
users' questions.
"""

from __future__ import annotations

import argparse
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0"
)

BUSINESS_SUBS = ("sysadmin", "msp", "healthcareIT", "smallbusiness", "ITManagers")
CONSUMER_SUBS = ("techsupport", "computerquestions", "HomeNetworking")

QUESTION_RE = re.compile(
    r"\?|^(how|why|what|which|help|should|can(?:not|'t)?|does|is there|any advice|looking for)\b",
    re.I,
)
MAX_AGE_H = 48
DEFAULT_OUT_DIR = "/home/anthony/Klaravex2.0/revenue-agents/outbox/forums/_harvest"
ATOM = "{http://www.w3.org/2005/Atom}"


def fetch_sub_rss(sub: str) -> list[dict] | str:
    url = f"https://www.reddit.com/r/{sub}/new/.rss"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        return f"r/{sub}: {exc}"
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return f"r/{sub}: bad feed ({exc})"

    now = datetime.now(timezone.utc)
    rows = []
    for entry in root.findall(f"{ATOM}entry"):
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        link_el = entry.find(f"{ATOM}link")
        url_ = link_el.get("href") if link_el is not None else ""
        published = entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated") or ""
        if not title or not url_:
            continue
        try:
            ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
            age_h = (now - ts).total_seconds() / 3600
        except ValueError:
            age_h = 0.0
        if age_h > MAX_AGE_H:
            continue
        if not QUESTION_RE.search(title):
            continue
        content = entry.findtext(f"{ATOM}content") or ""
        snippet = re.sub(r"<[^>]+>", " ", content)
        snippet = re.sub(r"\s+", " ", snippet).strip()[:220]
        rows.append({
            "sub": sub,
            "title": title[:160],
            "url": url_,
            "age_h": round(age_h, 1),
            "snippet": snippet,
        })
    return rows


def harvest(subs: tuple[str, ...], per_sub: int = 4, delay_s: float = 12.0) -> tuple[list[dict], list[str]]:
    """Anonymous RSS is limited to roughly one request per ~10s — pace accordingly."""
    rows: list[dict] = []
    errors: list[str] = []
    for i, sub in enumerate(subs):
        out = fetch_sub_rss(sub)
        if isinstance(out, str) and "429" in out:
            time.sleep(20)
            out = fetch_sub_rss(sub)
        if isinstance(out, str):
            errors.append(out)
        else:
            rows.extend(sorted(out, key=lambda r: r["age_h"])[:per_sub])
        if i < len(subs) - 1:
            time.sleep(delay_s)
    return rows, errors


def render(business: list[dict], consumer: list[dict], errors: list[str]) -> str:
    day = date.today().isoformat()
    lines = [
        f"# Live forum questions — {day}",
        "",
        f"Real, open threads from Reddit RSS (last {MAX_AGE_H}h, question-shaped,",
        "newest first). Use these URLs verbatim in THREAD blocks. Answer the",
        "actual question asked — do not invent thread content beyond the",
        "title/snippet shown.",
        "",
    ]
    for label, rows in (("Business venues", business), ("Consumer venues", consumer)):
        lines += [f"## {label}", "", "| Sub | Age | Question | URL |", "|---|---|---|---|"]
        for r in rows:
            t = r["title"].replace("|", "/")
            lines.append(f"| r/{r['sub']} | {r['age_h']}h | {t} | {r['url']} |")
        if not rows:
            lines.append("| — | — | (harvest empty — fall back to search-query targets) | — |")
        lines.append("")
    if errors:
        lines += ["## Harvest errors", ""] + [f"- {e}" for e in errors] + [""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest live Reddit question threads for forums agent")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--per-sub", type=int, default=4)
    args = parser.parse_args()

    business, err_b = harvest(BUSINESS_SUBS, per_sub=args.per_sub)
    consumer, err_c = harvest(CONSUMER_SUBS, per_sub=args.per_sub)
    body = render(business, consumer, err_b + err_c)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date.today().isoformat()}-live-threads.md"
    out_path.write_text(body, encoding="utf-8")
    print(f"wrote {out_path} ({len(business)} business + {len(consumer)} consumer threads)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
