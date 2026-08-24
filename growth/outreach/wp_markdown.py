"""Minimal markdown → HTML for WordPress draft bodies."""

from __future__ import annotations

import re


def inline(s: str) -> str:
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(md: str) -> str:
    out: list[str] = []
    for block in re.split(r"\n{2,}", md):
        block = block.strip()
        if not block:
            continue
        hm = re.match(r"^(#{1,4})\s+(.*)$", block.splitlines()[0])
        if hm and len(block.splitlines()) == 1:
            lvl = len(hm.group(1)) + 1
            out.append(f"<h{min(lvl, 6)}>{inline(hm.group(2))}</h{min(lvl, 6)}>")
            continue
        if all(l.lstrip().startswith(("- ", "* ")) for l in block.splitlines()):
            items = "".join(
                f"<li>{inline(l.lstrip()[2:].strip())}</li>" for l in block.splitlines()
            )
            out.append(f"<ul>{items}</ul>")
            continue
        out.append(f"<p>{inline(' '.join(block.splitlines()))}</p>")
    return "\n".join(out)
