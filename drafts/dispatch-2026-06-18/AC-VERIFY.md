# AC-VERIFY — End-to-End Outbound Pipeline Verification Gate

> **GATING RULE:** No outbound campaign goes live until every item below is ✅ GREEN.
> Per Anthony 2026-06-12T05:58 — *do not send leads out if things are not working.*

---

## Pre-flight: Environment Setup

```bash
# Load secrets from your secrets manager before running any checks
export $(cat .env.production | grep -v '^#' | xargs)

# Required env vars — confirm all are non-empty before proceeding
REQUIRED_VARS=(
  DATABASE_URL CELERY_BROKER_URL LOKI_INTERNAL_SECRET
  MS_GRAPH_CLIENT_ID MS_GRAPH_CLIENT_SECRET MS_GRAPH_TENANT_ID
  TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_PHONE_NUMBER ANTHONY_MOBILE_E164
  VAPI_API_KEY STRIPE_WEBHOOK_SECRET CALENDLY_WEBHOOK_SECRET
  RESEND_API_KEY SMTP_FROM_EMAIL
)
for v in "${REQUIRED_VARS[@]}"; do
  [[ -z "${!v}" ]] && echo "❌ MISSING: $v" || echo "✅ SET: $v"
done
```

---

## SECTION 1 — Internal Data Plane

### ✅ Item 1 — T-INF-06: leads table accessible, no UndefinedTableError (30 min)

```bash
# 1a. Confirm table exists
psql "$DATABASE_URL" -c "\dt leads"

# 1b. Confirm schema is correct
psql "$DATABASE_URL" -c "\d leads"

# 1c. Tail klaravex_worker logs for 30 min, fail on UndefinedTableError
DURATION=1800  # 30 minutes
START=$(date +%s)
echo "Monitoring klaravex_worker logs for 30 min — started $(date)"
docker logs -f klaravex_worker 2>&1 | while IFS= read -r line; do
  echo "$line"
  if echo "$line" | grep -q "UndefinedTableError"; then
    echo "❌ FAIL: UndefinedTableError detected at $(date)"
    exit 1
  fi
  [[ $(( $(date +%s) - START )) -ge $DURATION ]] && echo "✅ PASS: 30 min clean" && exit 0
done
```

**Rollback:** If UndefinedTableError fires:
```bash
# Re-run migrations
alembic upgrade head
# Verify
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM leads;"
```

---

### ✅ Item 2 — T14.4: mailbox_poll succeeds for 30 min

```bash
# 1. Confirm task is registered
celery -A app.celery inspect registered | grep mailbox_poll

# 2. Trigger one manual run and check exit
celery -A app.celery call tasks.mailbox_poll
sleep 10
celery -A app.celery inspect active

# 3. Monitor Celery logs for errors over 30 min
DURATION=1800
START=$(date +%s)
docker logs -f klaravex_worker 2>&1 | grep -i "mailbox_poll" | while IFS= read -r line; do
  echo "$line"
  if echo "$line" | grep -qiE "ERROR|FAILED|Retry"; then
    echo "❌ FAIL: mailbox_poll error at $(date)"
    exit 1
  fi
  [[ $(( $(date +%s) - START )) -ge $DURATION ]] && echo "✅ PASS: 30 min clean" && exit 0
done
```

**Rollback:** If mailbox_poll fails:
```bash
# Pause beat schedule to stop retry storm
celery -A app.celery control cancel_consumer mailbox_poll
# Inspect last exception
celery -A app.celery inspect reserved
```

---

### ✅ Item 3 — social_media.route_qualified_social_posts runs clean for 1 hour

```bash
# 1. Confirm task is scheduled in beat
celery -A app.celery inspect scheduled | grep route_qualified_social_posts

# 2. Monitor for 1 hour
DURATION=3600
START=$(date +%s)
docker logs -f klaravex_worker 2>&1 | grep "route_qualified_social_posts" | while IFS= read -r line; do
  echo "$line"
  if echo "$line" | grep -qiE "ERROR|FAILED|Traceback|Retry"; then
    echo "❌ FAIL at $(date): $line"
    exit 1
  fi
  [[ $(( $(date +%s) - START )) -ge $DURATION ]] && echo "✅ PASS: 1 hour clean" && exit 0
done
```

---

### ✅ Item 4 — All Celery tasks complete without retries (30 min)

```bash
# 1. Check current retry queue depth
celery -A app.celery inspect reserved
celery -A app.celery inspect active

# 2. Query Celery result backend for retries in last 30 min
# (adjust for your backend — Redis example)
redis-cli KEYS "celery-task-meta-*" | xargs -I{} redis-cli GET {} | \
  python3 -c "
import sys, json
retries = []
for line in sys.stdin:
    line = line.strip()
    if not line or line == 'nil': continue
    try:
        d = json.loads(line)
        if d.get('status') == 'RETRY':
            retries.append(d)
    except: pass
if retries:
    print(f'❌ FAIL: {len(retries)} tasks in RETRY state')
    for r in retries: print(r)
else:
    print('✅ PASS: No tasks in RETRY state')
"

# 3. Confirm Flower dashboard (if deployed)
curl -s http://localhost:5555/api/tasks?state=RETRY | python3 -m json.tool
```

**Rollback:** Purge stuck retry queue:
```bash
celery -A app.celery purge -f
# WARNING: this drops all queued tasks — only if retry storm is unrecoverable
```

---

## SECTION 2 — Outbound Infrastructure

### ✅ Item 5 — Microsoft Graph send_email test

```bash
# Get OAuth token
MS_TOKEN=$(curl -s -X POST \
  "https://login.microsoftonline.com/${MS_GRAPH_TENANT_ID}/oauth2/v2.0/token" \
  -d "client_id=${MS_GRAPH_CLIENT_ID}" \
  -d "client_secret=${MS_GRAPH_CLIENT_SECRET}" \
  -d "scope=https://graph.microsoft.com/.default" \
  -d "grant_type=client_credentials" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

[[ -z "$MS_TOKEN" ]] && echo "❌ FAIL: Could not obtain MS Graph token" && exit 1

# Send test email
HTTP_STATUS=$(curl -s -o /tmp/ms_graph_response.json -w "%{http_code}" \
  -X POST "https://graph.microsoft.com/v1.0/users/${SMTP_FROM_EMAIL}/sendMail" \
  -H "Authorization: Bearer ${MS_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "message": {
      "subject": "AC-VERIFY Test — MS Graph",
      "body": {"contentType": "Text", "content": "AC-VERIFY test send. Timestamp: '"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'"},
      "toRecipients": [{"emailAddress": {"address": "astewart@klaravex.com"}}]
    }
  }')

[[ "$HTTP_STATUS" == "202" ]] \
  && echo "✅ PASS: MS Graph send_email returned 202" \
  || { echo "❌ FAIL: HTTP $HTTP_STATUS"; cat /tmp/ms_graph_response.json; }
```

**Rollback:** If token fails, re-check app registration in Azure AD:
```bash
# Verify client secret not expired
az ad app credential list --id "$MS_GRAPH_CLIENT_ID"
```

---

### ✅ Item 6 — Twilio SMS test send

```bash
SMS_RESPONSE=$(curl -s -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json" \
  -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}" \
  --data-urlencode "From=${TWILIO_PHONE_NUMBER}" \
  --data-urlencode "To=${ANTHONY_MOBILE_E164}" \
  --data-urlencode "Body=AC-VERIFY test SMS $(date -u +%Y-%m-%dT%H:%M:%SZ)")

SMS_SID=$(echo "$SMS_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('sid',''))")
SMS_ERR=$(echo "$SMS_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error_code',''))")

[[ -n "$SMS_SID" && -z "$SMS_ERR" ]] \
  && echo "✅ PASS: SMS sent — SID $SMS_SID" \
  || { echo "❌ FAIL: $SMS_RESPONSE"; }

# Poll for delivery status (wait up to 30s)
sleep 15
curl -s "https://api.twilio.com/2010-04-01/Accounts/${TWILIO_ACCOUNT_SID}/Messages/${SMS_SID}.json" \
  -u "${TWILIO_ACCOUNT_SID}:${TWILIO_AUTH_TOKEN}" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('status'); print(f'SMS status: {s}'); exit(0 if s in ['delivered','sent'] else 1)"
```

**Rollback:** If SMS fails with error 21606 (not A2P registered) — see Item 20.

---

### ✅ Item 7 — Vapi call infrastructure responding (T-INF-03)

```bash
# 1. Confirm API key is present (T-INF-03 confirmed)
[[ -n "$VAPI_API_KEY" ]] && echo "✅ Key present" || echo "❌ VAPI_API_KEY missing"

# 2. Verify API reachability
VAPI_STATUS=$(curl -s -o /tmp/vapi_resp.json -w "%{http_code}" \
  -H "Authorization: Bearer ${VAPI_API_KEY}" \
  "https://api.vapi.ai/assistant")

[[ "$VAPI_STATUS" == "200" ]] \
  && echo "✅ PASS: Vapi API reachable (200)" \
  || { echo "❌ FAIL: HTTP $VAPI_STATUS"; cat /tmp/vapi_resp.json; }

# 3. Initiate test outbound call (use a test/staging assistant ID)
# Replace VAPI_TEST_ASSISTANT_ID and VAPI_TEST_PHONE_NUMBER_ID with your values
curl -s -X POST "https://api.vapi.ai/call/phone" \
  -H "Authorization: Bearer ${VAPI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "assistantId": "'"${VAPI_TEST_ASSISTANT_ID}"'",
    "phoneNumberId": "'"${VAPI_TEST_PHONE_NUMBER_ID}"'",
    "customer": {
      "number": "'"${ANTHONY_MOBILE_E164}"'",
      "name": "AC-VERIFY Test"
    }
  }' | python3 -c "
import sys, json
d = json.load(sys.stdin)
if d.get('id'):
    print(f'✅ PASS: Vapi call initiated — ID {d[\"id\"]}')
else:
    print(f'❌ FAIL: {d}')
    exit(1)
"
```

---

### ✅ Item 8 — Stripe webhook reachable + verified

```bash
# 1. Confirm webhook endpoint is reachable
WEBHOOK_URL="https://api.klaravex.com/webhooks/stripe"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" -d '{}')
# Expect 400 (missing signature) not 404/502
[[ "$HTTP_STATUS" =~ ^(400|401)$ ]] \
  && echo "✅ PASS: Webhook endpoint reachable (returned $HTTP_STATUS as expected for unsigned request)" \
  || echo "❌ FAIL: Unexpected HTTP $HTTP_STATUS — endpoint may be down"

# 2. Replay a test webhook via Stripe CLI
stripe listen --forward-to "$WEBHOOK_URL" &
STRIPE_PID=$!
sleep 3
stripe trigger payment_intent.created
sleep 5

# 3. Check app logs for successful signature verification
docker logs klaravex_api --since 30s 2>&1 | grep -i "stripe" | tail -20
docker logs klaravex_api --since 30s 2>&1 | grep -iE "webhook.*verified|signature.*valid" \
  && echo "✅ PASS: Stripe webhook signature verified" \
  || echo "❌ FAIL: No signature verification log found"

kill $STRIPE_PID 2>/dev/null
```

**Rollback:** If signature fails:
```bash
# Re-sync webhook secret from Stripe dashboard
stripe webhooks list
# Update STRIPE_WEBHOOK_SECRET in secrets manager and redeploy
```

---

### ✅ Item 9 — Calendly webhook signature verification (V5)

```bash
# 1. Confirm secret is set
[[ -n "$CALENDLY_WEBHOOK_SECRET" ]] \
  && echo "✅ CALENDLY_WEBHOOK_SECRET present" \
  || echo "❌ MISSING: CALENDLY_WEBHOOK_SECRET"

# 2. Construct a test payload and compute expected HMAC-SHA256 signature
PAYLOAD='{"event":"invitee.created","payload":{"event_type":{"name":"AC-VERIFY Test"}}}'
TIMESTAMP=$(date +%s)
SIGNED_CONTENT="${TIMESTAMP}.${PAYLOAD}"
EXPECTED_SIG=$(echo -n "$SIGNED_CONTENT" | \
  openssl dgst -sha256 -hmac "$CALENDLY_WEBHOOK_SECRET" | awk '{print $2}')

# 3. Send to your webhook endpoint
WEBHOOK_URL="https://api.klaravex.com/webhooks/calendly"
HTTP_STATUS=$(curl -s -o /tmp/calendly_resp.json -w "%{http_code}" \
  -X POST "$WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "Calendly-Webhook-Signature: t=${TIMESTAMP},v1=${EXPECTED_SIG}" \
  -d "$PAYLOAD")

[[ "$HTTP_STATUS" == "200" ]] \
  && echo "✅ PASS: Calendly webhook accepted (200)" \
  || { echo "❌ FAIL: HTTP
