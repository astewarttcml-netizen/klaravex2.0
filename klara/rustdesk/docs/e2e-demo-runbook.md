# Full E2E Demo Runbook: Phone → Klara → RustDesk → Repair → Close

**Task 16.19** — Step-by-step demo script with all tool calls, expected responses,
and verification checkpoints. Executable manually as a runbook.

**Phone number:** +1 (424) 348-6010
**Estimated duration:** 8–12 minutes end-to-end

---

## Prerequisites

Before running the demo:

- [ ] Controller API running on rig (`python -m uvicorn infra.main:app --port 8000`)
- [ ] `KLX_REMOTE_KILL_TOKEN` set in env (operator tray auth)
- [ ] `KLX_RDSHIM_BIN` set if testing real shim transport (omit for stub)
- [ ] Operator tray running on rig (`python -m rustdesk_controller.operator_tray`)
- [ ] Vapi assistant "Klaravex Triage" active (id: `8b2cac12-4918-48a0-a583-630ae770f7f5`)
- [ ] RustDesk client installed on the test "customer" machine
- [ ] Azure `klaravex-db` reachable (for session + consent persistence)
- [ ] Second phone or VoIP line for the "customer" caller

---

## Phase 1: Phone Call → Klara Answers

### Step 1.1 — Dial In

**Action:** Call +1 (424) 348-6010 from the test customer phone.

**Expected:**
- Vapi routes to "Klaravex Triage" assistant
- Silent VIP gate runs first (`vapi_vip_access`)
- VIP gate returns `is_vip: false` (test number not in VIP list)
- Klara speaks the greeting:
  > "Hi, you've reached Klah-ruh-vex support. This is Klah-ruh, your AI tech support assistant. Are you calling about personal home technical support, or business IT support?"

**Verify:** ✅ Greeting spoken, pronunciation correct ("KLAH-ruh-vex"), no VIP route triggered.

### Step 1.2 — Consumer Routing

**Action:** Caller says: "Personal — my laptop."

**Expected:**
- Klara identifies consumer path
- Proceeds to Step 1 (device identification):
  > "Got it. And what device is giving you trouble — a Windows computer, a Mac, an iPhone or iPad, an Android phone, or something else?"

**Verify:** ✅ No transfer to Biz Intake. Consumer diagnostic flow started.

---

## Phase 2: Diagnosis

### Step 2.1 — Device Identification

**Action:** Caller says: "It's a Windows laptop."

**Expected:**
- Klara records device = "windows"
- Moves to Step 2:
  > "And what's it doing — or not doing — today?"

### Step 2.2 — Issue Description

**Action:** Caller says: "My WiFi won't connect. It was working yesterday."

**Expected:**
- Klara maps to "Internet / WiFi not working"
- Moves to Step 3 (confirm back):
  > "So your Windows laptop won't connect to the WiFi at home, and it was working fine yesterday — is that right?"

### Step 2.3 — Confirmation

**Action:** Caller says: "Yes, that's right."

**Verify:** ✅ Issue confirmed. Klara does NOT call `start_troubleshooting` yet (payment gate).

---

## Phase 3: Payment

### Step 3.1 — Quote $29

**Expected:** Klara quotes:
> "Okay, I understand what's going on. Our fix sessions are a flat $29 — that covers everything we'll do today, no matter how long it takes, and you get a full refund if we don't get it sorted. What's the best email address to send the payment link to?"

### Step 3.2 — Collect Email

**Action:** Caller spells: "T-E-S-T at K-L-A-R-A-V-E-X dot C-O-M"

**Expected:**
- Klara reads back NATO-phonetics
- Confirms: "That's T as in Tango, E as in Echo, S as in Sierra, T as in Tango — at klaravex dot com. Is that right?"

**Action:** Caller says: "Yes."

### Step 3.3 — Send Payment Link

**Tool call (Klara → Vapi → backend):**
```json
{
  "tool": "send_payment_link",
  "params": {
    "sku": "per-incident",
    "caller_email_letters": ["t","e","s","t","at","klaravex","dot","com"],
    "caller_phone": "+1XXXXXXXXXX",
    "call_sid": "<vapi-call-id>",
    "delivery": "email"
  }
}
```

**Expected response:**
```json
{
  "status": "ok",
  "delivery_summary": "Payment link sent to test@klaravex.com via email.",
  "stripe_session_id": "cs_XXXX..."
}
```

**Klara says:**
> "Okay, I just sent it from support at klaravex dot com. It should arrive in a minute or two. Tap the green Pay button when you see it. I'll be right here while you do."

### Step 3.4 — Payment Polling

**Tool call (repeated every ~8-10s):**
```json
{
  "tool": "check_payment_status",
  "params": {
    "call_sid": "<vapi-call-id>"
  }
}
```

**Klara fills silence:** "How long has this been bothering you?" / "Is this your everyday computer?"

**Action (demo shortcut):** Complete the Stripe checkout in the test email.

**Expected response after payment:**
```json
{
  "paid": true,
  "amount": 3900,
  "customer_email": "test@klaravex.com"
}
```

**Verify:** ✅ Payment confirmed. Klara proceeds to Remote Session Setup.

---

## Phase 4: RustDesk Remote Session Setup

### Step 4.1 — RustDesk Installation Walk-Through

**Klara says:**
> "I need to see your screen to fix this. Have you heard of RustDesk? It's a free screen-sharing program."

> "Go to rustdesk dot com — that's R, U, S, T, D, E, S, K, dot com. Click the Download button for your computer."

> "Open the downloaded file. If Windows asks for permission, click Yes."

**Action (demo):** Customer machine already has RustDesk installed.
Caller says: "I already have it installed."

**Klara says:**
> "Perfect. You'll see a window with a big number at the top — it's nine digits. Can you read that to me?"

### Step 4.2 — Collect 9-Digit RustDesk ID

**Action:** Caller reads: "1, 2, 3, 4, 5, 6, 7, 8, 9"

**Klara reads back:**
> "That's 123, 456, 789. Is that right?"

**Action:** Caller confirms: "Yes."

### Step 4.3 — Start RustDesk Session

**Tool call (Klara → Vapi → backend):**
```json
{
  "tool": "start_rustdesk_session",
  "params": {
    "customer_email": "test@klaravex.com",
    "problem_summary": "Windows laptop WiFi won't connect",
    "customer_rustdesk_id": "123456789"
  }
}
```

**Expected response:**
```json
{
  "status": "ok",
  "session_id": "<12-char-hex>",
  "customer_rustdesk_id": "123456789",
  "instructions_for_klara": "The customer's RustDesk ID is 123456789. Tell them: 'I can see your screen now. Let me take a look at what's going on.' Then begin the diagnostic.",
  "relay_host": "<relay-host>",
  "recording_enabled": true,
  "warmup_task_name": "warmup-<session_id>"
}
```

**Klara says:**
> "Perfect, I can see your screen now. Let's get this fixed."

**Verify checkpoint:**
- [ ] Session created in memory (GET /api/remote-sessions/<session_id> returns 200)
- [ ] KillSwitch registered (killswitch_registry().get(session_id) is not None)
- [ ] Warmup task spawned
- [ ] Audit chain has entries: session creation
- [ ] Operator tray shows red icon (active session detected)

---

## Phase 5: AI-Driven Repair Loop

### Step 5.1 — Vision Predict → Confirm → Execute Cycle

**Tool call (Klara → Vapi → backend):**
```json
{
  "tool": "next_screen_action",
  "params": {
    "session_id": "<session_id>"
  }
}
```

**Possible responses:**

1. **`awaiting_first_frame`** — transport hasn't delivered a frame yet:
   ```json
   {
     "status": "awaiting_first_frame",
     "action_description": "Waiting for the customer helper to send the first frame..."
   }
   ```
   Klara asks: "Is the RustDesk window still open? You might see a permission prompt."

2. **`predicting`** — vision call dispatched:
   ```json
   {
     "status": "predicting",
     "action_description": "Vision call dispatched against the latest frame..."
   }
   ```
   Klara fills: "One moment while I look at your screen..."

3. **`awaiting_confirmation`** — prediction ready:
   ```json
   {
     "status": "awaiting_confirmation",
     "action_description": "I see the WiFi icon shows disconnected. I want to right-click on it to open network settings.",
     "confidence": 0.87
   }
   ```
   Klara says: "I see the WiFi icon shows it's disconnected. I'd like to right-click on it to open your network settings — is that okay?"

### Step 5.2 — Customer Confirms Action

**Action:** Caller says: "Yes, go ahead."

**Tool call:**
```json
{
  "tool": "confirm_action",
  "params": {
    "session_id": "<session_id>",
    "confirmed": true
  }
}
```

**Expected response:**
```json
{
  "status": "ok",
  "executed": true,
  "rejection_streak": 0
}
```

**Verify:** ✅ InputEvent sent to customer machine via transport. Audit row: `action_executed`.

### Step 5.3 — Repeat Predict/Confirm Loop

Repeat steps 5.1–5.2 for each repair action (typically 3–6 cycles):
- Open network settings
- Click "Forget" on saved WiFi network
- Click WiFi network name
- Enter WiFi password
- Verify connection

**Abort conditions (automatic):**
- 2 consecutive rejections → killswitch fires (`auto_abort_rejections`)
- Vision confidence < 0.6 → killswitch fires (`auto_abort_low_conf`)
- 60s no customer confirm → killswitch fires (`auto_abort_timeout`)

---

## Phase 6: Session Close

### Step 6.1 — Issue Resolved

**Klara says:**
> "Your WiFi is connected now. Can you try opening a website to make sure everything's working?"

**Action:** Caller confirms: "Yes, it's loading! Thank you!"

### Step 6.2 — End Session

**Tool call:**
```json
{
  "tool": "end_rustdesk_session",
  "params": {
    "session_id": "<session_id>",
    "outcome": "fixed"
  }
}
```

**Expected response:**
```json
{
  "status": "ok",
  "summary": {
    "enabled": true,
    "events_written": 12,
    "audit_chain_intact": true
  }
}
```

**Verify checkpoint:**
- [ ] Session state = `ended_fixed`
- [ ] Transport closed
- [ ] Frame pump stopped
- [ ] Warmup task cancelled (if still alive)
- [ ] Audit chain intact (`verify() == true`)
- [ ] Session recording archived to `.loki/remote-sessions/<session_id>/`
- [ ] KillSwitch deregistered from registry
- [ ] Operator tray returns to grey icon

### Step 6.3 — Call Close

**Klara says:**
> "Wonderful — your WiFi is back up and running. You'll get a confirmation email at test at klaravex dot com. Is there anything else I can help with today?"

**Action:** Caller says: "No, that's everything. Thank you!"

**Klara says:**
> "You're welcome! Have a wonderful rest of your day. Goodbye."

---

## Phase 7: Killswitch Verification (Parallel Track)

At any point during phases 4–6, verify the killswitch works:

### Test 7.1 — Operator Tray Kill

**Action:** Right-click tray icon → "Kill 1 active session"

**Expected:**
- POST /api/remote-sessions/<session_id>/kill with `fired_by=server_override`
- Session terminates within 1 second
- Audit row: `killswitch_fired` with `fired_by=server_override`
- Tray icon returns to grey

### Test 7.2 — Hotkey Kill

**Action:** Press Ctrl+Shift+Escape on rig

**Expected:**
- Same as 7.1 but triggered by global hotkey
- Log: "hotkey Ctrl+Shift+Escape detected — killing sessions"

### Test 7.3 — Customer Kill (if helper supports it)

**Action:** Customer clicks STOP in helper banner or presses Ctrl+Shift+Escape

**Expected:**
- POST /api/remote-sessions/<session_id>/kill/customer
- `fired_by=customer_tray` or `customer_hotkey` depending on path
- Session terminates within 1 second

---

## Verification Checklist (Post-Demo)

```bash
# 1. Check audit chain integrity
python3 -c "
import json
from pathlib import Path
sink = list(Path('.loki/remote-sessions').iterdir())[-1]
lines = (sink / 'audit.jsonl').read_text().strip().split('\n')
print(f'Audit entries: {len(lines)}')
for line in lines:
    entry = json.loads(line)
    print(f'  {entry[\"event_type\"]}: {entry.get(\"payload\", {})}')
"

# 2. Check DB row
# psql -h klaravex-db-r2.postgres.database.azure.com -U klaravexadmin -d klaravex
# SELECT session_id, state, outcome, killed, killed_by, kill_reason
# FROM klaravex_remote_sessions
# ORDER BY started_at DESC LIMIT 1;

# 3. Check recording archive
ls -la .loki/remote-sessions/*/

# 4. Verify operator tray saw the session
# Check tray logs for "active session(s)" polling messages

# 5. Run test suite (regression)
python3 -m pytest infra/rustdesk_controller/tests/ -q
```

---

## Failure Modes & Recovery

| Failure | Symptom | Recovery |
|---------|---------|----------|
| Vapi doesn't answer | No greeting after 10s | Check Vapi dashboard for assistant status |
| Payment link doesn't arrive | Caller doesn't see email | Verify Stripe webhook, check spam |
| RustDesk ID invalid | `start_rustdesk_session` rejects pattern | Re-read ID from caller, must be 9 digits |
| Transport won't connect | `warmup_failed` audit row | Check relay host, `--probe` mode |
| Vision returns low confidence | Auto-abort fires | Expected if screen is unusual; retry or handoff |
| DB unreachable | Session created but not persisted | Consent gate may block; check Azure connectivity |
| Killswitch doesn't fire | Session persists after kill attempt | Check `KLX_REMOTE_KILL_TOKEN` matches |

---

## Demo Shortcuts (for internal testing)

1. **Skip payment:** Set `KLARAVEX_SKIP_PAYMENT=1` in env (dev only)
2. **Skip RustDesk install:** Use a machine that already has RustDesk
3. **Stub transport:** Omit `KLX_RDSHIM_BIN` — session runs against stub (no real screen frames)
4. **Dry-run mode:** `python3 -m rustdesk_controller --email test@klaravex.com --region us --goal "fix wifi" --cycles 3`
