"""Burn readable end-card text onto short-form social videos (ffmpeg)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
)


def _font() -> str:
    for p in FONT_CANDIDATES:
        if Path(p).is_file():
            return p
    raise FileNotFoundError("No TrueType font found for ffmpeg drawtext")


def _esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
    )


def burn_endcard(
    src: Path,
    dst: Path,
    *,
    lines: list[str],
    start_at: float = 3.2,
    bg_alpha: float = 0.72,
) -> None:
    font = _font()
    filters: list[str] = []
    y_base = 0.68
    for i, line in enumerate(lines):
        y = y_base + i * 0.08
        filters.append(
            "drawtext="
            f"fontfile={font}:"
            f"text='{_esc(line)}':"
            "fontsize=34:"
            "fontcolor=white:"
            "borderw=2:bordercolor=0x111111:"
            f"x=(w-text_w)/2:y=h*{y}:"
            f"enable='gte(t\\,{start_at})'"
        )
    # Dark band behind text for legibility
    filters.insert(
        0,
        f"drawbox=x=0:y=ih*{y_base - 0.04}:w=iw:h=ih*{0.08 * len(lines) + 0.12}:"
        f"color=black@{bg_alpha}:t=fill:enable='gte(t\\,{start_at})'",
    )
    vf = ",".join(filters)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(src),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(tmp_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        shutil.move(str(tmp_path), str(dst))
    except subprocess.CalledProcessError as exc:
        if tmp_path.exists():
            tmp_path.unlink()
        raise RuntimeError(exc.stderr or exc.stdout or "ffmpeg failed") from exc


PRESETS: dict[str, list[str]] = {
    "consumer-tiktok": [
        "personal.klaravex.com",
        "Solo $29 · Family $39",
    ],
    "consumer-youtube": [
        "personal.klaravex.com",
        "Solo $29 · Family $39",
    ],
    "business-tiktok": [
        "klaravex.com",
        "M365 · Google · MFA",
    ],
    "business-youtube": [
        "klaravex.com/hipaa-readiness",
        "M365 or Google + MFA",
    ],
}


def main() -> None:
    p = argparse.ArgumentParser(description="Burn end-card text onto social video")
    p.add_argument("src", type=Path)
    p.add_argument("dst", type=Path)
    p.add_argument(
        "--preset",
        choices=sorted(PRESETS),
        help="Named line preset (overrides --line)",
    )
    p.add_argument("--line", action="append", default=[], help="Custom end-card line")
    p.add_argument("--start-at", type=float, default=3.2)
    args = p.parse_args()
    lines = PRESETS[args.preset] if args.preset else args.line
    if not lines:
        raise SystemExit("Provide --preset or at least one --line")
    burn_endcard(args.src, args.dst, lines=lines, start_at=args.start_at)
    print(f"Wrote {args.dst}")


if __name__ == "__main__":
    main()
