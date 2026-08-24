"""Print the Upwork OAuth setup path. Does not start a browser by default."""

from __future__ import annotations

import argparse
import sys

from growth.upwork.oauth import APPLY_URL, authorize_url, client_configured, public_status, redirect_uri


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Upwork GraphQL OAuth helper")
    p.add_argument("--authorize-url", action="store_true", help="print the live authorize URL (needs client id)")
    args = p.parse_args(argv)
    st = public_status()
    print("Upwork GraphQL job search (official API — no scraping)")
    print(f"1. Create an OAuth 2.0 app: {APPLY_URL}")
    print("2. Callback URL (exact):", redirect_uri())
    print("3. GraphQL permission: Read marketplace Job Postings")
    print("4. Connections → Upwork → paste Client ID + Secret → Authorize")
    print(f"client_configured={st['client_configured']} token_present={st['token_present']}")
    if args.authorize_url:
        if not client_configured():
            print("missing client id/secret", file=sys.stderr)
            return 2
        print(authorize_url()["authorize_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
