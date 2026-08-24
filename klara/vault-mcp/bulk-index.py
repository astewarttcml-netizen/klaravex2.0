#!/usr/bin/env python3
"""
bulk-index.py — One-time bulk ingestion of vault .md files into note_submissions.
The vault-mcp background worker handles embedding generation (5 notes/batch, ~10s cadence).

Usage:
    python3 bulk-index.py --db-url "postgresql://user:pass@host:5432/db"
    python3 bulk-index.py --db-url "..." --dry-run       # count only, no writes
    python3 bulk-index.py --db-url "..." --vault-path /custom/path
"""

import os
import sys
import json
import hashlib
import argparse
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Dependency bootstrap
# ---------------------------------------------------------------------------
try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    print("psycopg2 not found — installing psycopg2-binary...", flush=True)
    ret = os.system("pip3 install psycopg2-binary -q --break-system-packages 2>/dev/null || pip3 install psycopg2-binary -q")
    if ret != 0:
        sys.exit("ERROR: could not install psycopg2-binary")
    import psycopg2
    from psycopg2.extras import execute_values


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def derive_title(path: Path, content: str) -> Optional[str]:
    """Extract first H1 heading; fall back to humanised filename."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return path.stem.replace("-", " ").replace("_", " ").title()


def collect_files(vault_root: Path) -> list[Path]:
    files = [
        f for f in sorted(vault_root.rglob("*.md"))
        if ".git" not in f.parts
    ]
    return files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-index vault notes into Klara AI note_submissions")
    parser.add_argument("--vault-path",  default="/home/anthony/.claude/knowledge/klaravex-vault",  help="Root of vault git repo")
    parser.add_argument("--db-url",      required=True,               help="PostgreSQL connection string")
    parser.add_argument("--batch-size",  type=int, default=50,        help="INSERT batch size (default: 50)")
    parser.add_argument("--dry-run",     action="store_true",         help="Print files; do not insert")
    parser.add_argument("--max-chars",   type=int, default=32_000,    help="Truncate content at N chars (default: 32000)")
    args = parser.parse_args()

    vault_root = Path(args.vault_path)
    if not vault_root.is_dir():
        sys.exit(f"ERROR: vault path not found: {vault_root}")

    files = collect_files(vault_root)
    print(f"Vault: {vault_root}")
    print(f"Found: {len(files)} .md files")

    if args.dry_run:
        for f in files:
            print(f"  {f.relative_to(vault_root)}")
        return

    # -----------------------------------------------------------------------
    # Connect
    # -----------------------------------------------------------------------
    try:
        conn = psycopg2.connect(args.db_url)
    except Exception as e:
        sys.exit(f"ERROR: cannot connect to DB: {e}")

    conn.autocommit = False
    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # Load skip sets
    # -----------------------------------------------------------------------
    cur.execute("SELECT note_path FROM vault_embeddings")
    already_indexed: set[str] = {r[0] for r in cur.fetchall()}
    print(f"Already embedded:   {len(already_indexed)}")

    cur.execute("""
        SELECT metadata->>'note_path'
        FROM   note_submissions
        WHERE  status IN ('pending', 'processing')
          AND  metadata->>'note_path' IS NOT NULL
    """)
    already_queued: set[str] = {r[0] for r in cur.fetchall() if r[0]}
    print(f"Already queued:     {len(already_queued)}")

    skip_set = already_indexed | already_queued

    # -----------------------------------------------------------------------
    # Build batch
    # -----------------------------------------------------------------------
    rows: list[tuple] = []
    skipped = 0
    read_errors = 0

    for f in files:
        rel = str(f.relative_to(vault_root))

        if rel in skip_set:
            skipped += 1
            continue

        try:
            raw = f.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as e:
            print(f"  WARN: cannot read {rel}: {e}")
            read_errors += 1
            continue

        if not raw:
            skipped += 1
            continue

        content  = raw[:args.max_chars] if len(raw) > args.max_chars else raw
        title    = derive_title(f, content)
        metadata = json.dumps({"note_path": rel, "note_title": title})

        rows.append((content, metadata, "pending"))

    print(f"To queue:           {len(rows)}")
    print(f"Skipped:            {skipped}  |  Read errors: {read_errors}")

    if not rows:
        print("\nNothing to insert — all notes already indexed or queued.")
        cur.close()
        conn.close()
        return

    # -----------------------------------------------------------------------
    # Insert in batches
    # -----------------------------------------------------------------------
    inserted = 0
    for i in range(0, len(rows), args.batch_size):
        batch = rows[i:i + args.batch_size]
        execute_values(
            cur,
            "INSERT INTO note_submissions (content, metadata, status) VALUES %s",
            batch
        )
        conn.commit()
        inserted += len(batch)
        pct = inserted / len(rows) * 100
        print(f"  Inserted {inserted}/{len(rows)} ({pct:.0f}%)", end="\r", flush=True)

    print(f"\n✓ Queued {inserted} notes for embedding.")

    cur.close()
    conn.close()

    secs = (inserted / 5) * 10
    mins = secs / 60
    print(f"Estimated embedding time: ~{mins:.1f} min  ({inserted} notes ÷ 5/batch × 10s)")
    print("Monitor progress (US klaravex DB, schema vault):")
    print("  psql \"$DATABASE_URL\" -c \\")
    print("    \"SELECT status, COUNT(*) FROM note_submissions GROUP BY status ORDER BY status;\"")
    print("  psql \"$DATABASE_URL\" -c \\")
    print("    \"SELECT COUNT(*) FROM vault_embeddings;\"")


if __name__ == "__main__":
    main()
