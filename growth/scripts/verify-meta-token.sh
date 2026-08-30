#!/usr/bin/env bash
# Verify the Meta Ads token in growth/.env: read probes + write-scope check.
# Usage: growth/scripts/verify-meta-token.sh
set -euo pipefail
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
TOKEN=$(grep '^META_ADS_ACCESS_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
ACCT=$(grep '^META_AD_ACCOUNT_ID=' "$ENV_FILE" | cut -d= -f2-)
GRAPH=https://graph.facebook.com/v21.0

if [ -z "$TOKEN" ] || [ -z "$ACCT" ]; then
  echo "FAIL: META_ADS_ACCESS_TOKEN or META_AD_ACCOUNT_ID missing in $ENV_FILE"
  exit 1
fi

echo "1/3 read probe: /me/adaccounts"
curl -sf "$GRAPH/me/adaccounts?access_token=$TOKEN" > /dev/null \
  && echo "  OK — token valid, ad accounts reachable" \
  || { echo "  FAIL — token rejected"; exit 1; }

echo "2/3 insights probe: $ACCT/insights"
curl -sf -G "$GRAPH/$ACCT/insights" \
  --data-urlencode "access_token=$TOKEN" \
  --data-urlencode 'fields=campaign_name,impressions' --data-urlencode 'limit=1' > /dev/null \
  && echo "  OK — ads_read works" \
  || { echo "  FAIL — insights rejected (missing ads_read?)"; exit 1; }

echo "3/3 write-scope probe: campaign status round-trip"
# Toggle the first campaign to its CURRENT status — a no-op write that still
# requires ads_management, so it proves write scope without changing anything.
CID=$(python3 -c "import re;print(re.search(r'META_CAMPAIGNS = \((.*?)\)', open('$(dirname "$0")/../outreach/ads_dow.py').read()).group(1).split(',')[0].strip().strip('\"\''))")
CUR=$(curl -sf "$GRAPH/$CID?fields=status&access_token=$TOKEN" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])")
HTTP=$(curl -s -o /tmp/meta-write-probe.json -w '%{http_code}' -X POST "$GRAPH/$CID" \
  --data-urlencode "status=$CUR" --data-urlencode "access_token=$TOKEN")
if [ "$HTTP" = "200" ]; then
  echo "  OK — ads_management works (no-op write to $CID, status left $CUR)"
else
  echo "  FAIL — write returned HTTP $HTTP (missing ads_management scope):"
  head -c 300 /tmp/meta-write-probe.json
  exit 1
fi
echo "ALL OK — token is fully configured for read + write."
