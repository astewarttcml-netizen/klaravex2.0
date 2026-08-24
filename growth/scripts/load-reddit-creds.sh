#!/usr/bin/env bash
# Load Reddit credentials from 1Password into growth/.env — run this yourself:
#   bash /home/anthony/Klaravex2.0/growth/scripts/load-reddit-creds.sh
# Secrets go straight from `op` into the env file; nothing is printed.
set -euo pipefail

ENV_FILE="/home/anthony/Klaravex2.0/growth/.env"
VAULT="${VAULT:-Klaravex}"

# Find the Reddit item (title containing reddit or klaravexai)
ITEM_ID=$(op item list --vault "$VAULT" --format json |
  python3 -c "
import json, sys
for i in json.load(sys.stdin):
    t = (i.get('title') or '').lower()
    if 'reddit' in t or 'klaravexai' in t:
        print(i['id']); break
")
if [ -z "$ITEM_ID" ]; then
  echo "No Reddit/KlaravexAi item found in vault '$VAULT'." >&2
  echo "Create one with fields: username, password, client_id, client_secret" >&2
  exit 1
fi
echo "Found item: $(op item get "$ITEM_ID" --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["title"])')"

get_field() {
  op item get "$ITEM_ID" --fields "$1" --reveal 2>/dev/null | tr -d '\r\n' || true
}

USERNAME=$(get_field username)
PASSWORD=$(get_field password)
CLIENT_ID=$(get_field client_id)
CLIENT_SECRET=$(get_field client_secret)

set_env() { # key value
  local key="$1" val="$2"
  [ -z "$val" ] && { echo "  $key: (not in item — leaving as is)"; return; }
  if grep -q "^${key}=" "$ENV_FILE"; then
    # sed-safe replacement
    python3 - "$ENV_FILE" "$key" "$val" <<'PY'
import sys
path, key, val = sys.argv[1:4]
lines = open(path).read().splitlines()
out = [f"{key}={val}" if l.startswith(f"{key}=") else l for l in lines]
open(path, "w").write("\n".join(out) + "\n")
PY
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
  echo "  $key: set"
}

set_env REDDIT_USERNAME "$USERNAME"
set_env REDDIT_PASSWORD "$PASSWORD"
set_env REDDIT_CLIENT_ID "$CLIENT_ID"
set_env REDDIT_CLIENT_SECRET "$CLIENT_SECRET"

if [ -z "$CLIENT_ID" ] || [ -z "$CLIENT_SECRET" ]; then
  cat >&2 <<'EOF'

Missing client_id / client_secret — the account login alone is not enough.
Create the script app once (2 minutes):
  1. Log in to reddit.com as the account above
  2. https://www.reddit.com/prefs/apps → "create another app"
  3. type: script · name: klaravex-forums · redirect uri: http://localhost:8080
  4. Add the id (under the app name) and secret to the 1Password item as
     fields `client_id` / `client_secret`, then re-run this script.
EOF
  exit 2
fi

echo
echo "All four credentials set in growth/.env."
echo "Leave REDDIT_READONLY=true for a dry probe, or set false to go live."
