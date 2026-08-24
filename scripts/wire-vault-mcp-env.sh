#!/usr/bin/env bash
# wire-vault-mcp-env.sh
# ─────────────────────
# Copies DATABASE_URL from the live worker .env into Klaravex2.0/klara/vault-mcp/.env
# (gitignored), retargeted at the US tunnel with search_path=vault.
#
# Logs var NAMES only (never values) — satisfies credential-wiring policy.
# Does NOT start or stop containers.
set -euo pipefail

WORKER_ENV="${WORKER_ENV:-/home/anthony/klaravex/infra/docker-services/worker/.env}"
TARGET_ENV="${TARGET_ENV:-/home/anthony/Klaravex2.0/klara/vault-mcp/.env}"
EXAMPLE_ENV="/home/anthony/Klaravex2.0/klara/vault-mcp/.env.example"

if [[ ! -f "$WORKER_ENV" ]]; then
  echo "ERROR: worker env not found: $WORKER_ENV" >&2
  exit 1
fi

SRC_URL="$(grep -E '^DATABASE_URL=' "$WORKER_ENV" | head -1 | cut -d= -f2-)"
if [[ -z "$SRC_URL" ]]; then
  echo "ERROR: DATABASE_URL missing in $WORKER_ENV" >&2
  exit 1
fi

# Strip asyncpg driver prefix if present; node-pg wants postgresql://
URL="${SRC_URL/postgresql+asyncpg:\/\//postgresql:\/\/}"
# Container reaches tunnel via host.docker.internal (not 127.0.0.1)
URL="${URL//@host.docker.internal:15432/@host.docker.internal:15432}"
URL="${URL//@127.0.0.1:15432/@host.docker.internal:15432}"
# If URL still points at Azure FQDN, force tunnel host
if [[ "$URL" == *"postgres.database.azure.com"* ]]; then
  # rewrite host:port to tunnel
  URL="$(echo "$URL" | sed -E 's|@[^:/]+:[0-9]+/|@host.docker.internal:15432/|')"
fi

# Ensure sslmode + search_path=vault
if [[ "$URL" != *"sslmode="* ]]; then
  if [[ "$URL" == *"?"* ]]; then URL="${URL}&sslmode=require"; else URL="${URL}?sslmode=require"; fi
fi
if [[ "$URL" != *"search_path"* ]]; then
  URL="${URL}&options=-csearch_path%3Dvault"
fi

# Seed from example if target missing (preserves non-DB keys)
if [[ ! -f "$TARGET_ENV" && -f "$EXAMPLE_ENV" ]]; then
  cp "$EXAMPLE_ENV" "$TARGET_ENV"
fi
if [[ ! -f "$TARGET_ENV" ]]; then
  touch "$TARGET_ENV"
fi

# Upsert DATABASE_URL line
if grep -qE '^DATABASE_URL=' "$TARGET_ENV"; then
  # Use a temp file to avoid leaking into process list via sed -i quirks
  awk -v url="$URL" '
    BEGIN { done=0 }
    /^DATABASE_URL=/ { print "DATABASE_URL=" url; done=1; next }
    { print }
    END { if (!done) print "DATABASE_URL=" url }
  ' "$TARGET_ENV" > "${TARGET_ENV}.tmp"
  mv "${TARGET_ENV}.tmp" "$TARGET_ENV"
else
  printf '\nDATABASE_URL=%s\n' "$URL" >> "$TARGET_ENV"
fi

chmod 600 "$TARGET_ENV"

# Audit log — names only
echo "[wire-vault-mcp-env] wrote: DATABASE_URL (host=host.docker.internal:15432, search_path=vault)"
echo "[wire-vault-mcp-env] target: $TARGET_ENV (mode 600, gitignored)"
echo "[wire-vault-mcp-env] NEXT: enable Azure azure.extensions=VECTOR,PGCRYPTO then apply 01-schema.sql (see DEPLOY-US.md)"
