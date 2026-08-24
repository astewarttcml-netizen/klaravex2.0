"""
Prompt router — loads persona prompts and detects routing triggers.

Maps caller intent keywords to specialist personas so the voice pipeline
can hot-swap the system prompt mid-call when a caller's needs become clear.
"""
from __future__ import annotations

import os
import re

# Check both possible prompt locations (rig vs USA VM layout)
_candidates = [
    os.path.join(os.path.dirname(__file__), "..", "vapi-prompts"),  # rig: infra/vapi-prompts/
    os.path.join(os.path.dirname(__file__), "vapi-prompts"),        # USA VM: voice-pipeline/vapi-prompts/
]
PROMPTS_DIR = next((p for p in _candidates if os.path.isdir(p)), _candidates[0])

# ── Persona registry ──────────────────────────────────────────────────────
# Only files that actually exist on disk are registered.

_CANDIDATE_PERSONAS: dict[str, str] = {
    # IVR / Triage
    "triage":       "triage-en.md",
    "triage_es":    "triage-es.md",
    # Consumer squad
    "windows":      "windows-expert.md",
    "apple":        "apple-expert.md",
    "identity":     "identity-recovery.md",
    "mobile":       "mobile-expert.md",
    "smart_home":   "smart-home-network.md",
    # Business fork
    "biz_intake":   "biz-intake.md",
    # biz_engineer removed — existing clients route directly to pillar specialists
    # B2B pillar specialists
    "cipher":       "network-security-engineer.md",
    "echo":         "cloud-productivity-engineer.md",
    "lex":          "regulatory-compliance.md",
    "iris":         "ai-adoption.md",
    "atlas":        "atlas.md",
}

PERSONAS: dict[str, str] = {}
for _name, _filename in _CANDIDATE_PERSONAS.items():
    _path = os.path.join(PROMPTS_DIR, _filename)
    if os.path.isfile(_path):
        PERSONAS[_name] = os.path.abspath(_path)

# Voice mapping
# Triage: Klara female (EN/ES). Specialists: Chicago male (EN), specialist-es male (ES).
PERSONA_VOICES: dict[str, str] = {
    "triage": "klara-en",
    "triage_es": "klara-es",
}
DEFAULT_SPECIALIST_VOICE = "chicago-en"
DEFAULT_SPECIALIST_VOICE_ES = "specialist-es"


def get_voice_for_persona(persona: str, is_spanish: bool = False) -> str:
    """Get TTS voice. Spanish callers get Spanish voices for all personas."""
    if persona in PERSONA_VOICES:
        return PERSONA_VOICES[persona]
    return DEFAULT_SPECIALIST_VOICE_ES if is_spanish else DEFAULT_SPECIALIST_VOICE


# ── Routing keywords ─────────────────────────────────────────────────────
# Rules are grouped by the persona they fire FROM.

# From triage → consumer squad or biz_intake
_TRIAGE_RULES: list[tuple[list[str], str]] = [
    # Language detection — must be first so it fires before topic routing
    (["español", "spanish", "habla español", "en español", "no hablo inglés", "no english"], "triage_es"),
    # B2B — explicit existing client signals → straight to engineer auth
    (["existing client", "already a customer", "current client",
      "my account", "our account", "customer code", "client id",
      "account number"], "biz_intake"),
    # B2B — explicit new prospect signals → intake
    (["new client", "first time", "not a client yet", "looking for",
      "shopping around", "switching providers", "getting quotes"], "biz_intake"),
    (["windows", "pc", "laptop", "dell", "lenovo", "surface"], "windows"),
    (["mac", "macbook", "apple", "iphone", "ipad", "imac"],   "apple"),
    (["android", "samsung", "pixel", "galaxy", "tablet"],      "mobile"),
    (["wifi", "router", "network", "smart home", "mesh",
      "unifi", "ring", "alexa", "nest"],                       "smart_home"),
    (["scam", "hacked", "identity", "fraud", "phishing",
      "locked out", "stolen"],                                 "identity"),
]

# From biz_intake → pillar (if they mention a specific need after intake)
_BIZ_INTAKE_RULES: list[tuple[list[str], str]] = []

# From biz_engineer → pillar specialists
_BIZ_ENGINEER_RULES: list[tuple[list[str], str]] = [
    # cipher — network/security
    (["security", "firewall", "breach", "endpoint", "ransomware",
      "intrusion", "siem", "edr", "vulnerability", "penetration"],  "cipher"),
    # echo — M365 / cloud productivity
    (["microsoft", "365", "azure", "teams", "sharepoint",
      "outlook", "onedrive", "exchange", "entra", "intune"],        "echo"),
    # lex — regulatory / compliance readiness
    (["hipaa", "compliance", "soc 2", "soc2", "audit",
      "iso 27001", "nis2", "gdpr", "regulatory", "readiness"],     "lex"),
    # iris — AI adoption
    (["ai", "automation", "machine learning", "artificial intelligence",
      "chatbot", "copilot", "ai adoption"],                         "iris"),
    # atlas — strategic advisory (vCIO/vCISO)
    (["strategy", "vcio", "vciso", "advisory", "board",
      "roadmap", "budget review", "it strategy"],                   "atlas"),
]

# Map persona → its outbound routing rules
_ROUTE_TABLE: dict[str, list[tuple[list[str], str]]] = {
    "triage":       _TRIAGE_RULES,
    "biz_intake":   _BIZ_INTAKE_RULES,
    "biz_engineer": _BIZ_ENGINEER_RULES,
}


def load_persona(name: str) -> str:
    """Read a persona prompt file, strip HTML comments, return clean text."""
    path = PERSONAS.get(name)
    if not path:
        raise KeyError(f"Unknown persona: {name!r} (available: {list(PERSONAS)})")
    with open(path) as f:
        text = f.read()
    # Strip HTML comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Strip VIP silent-gate block (handled externally, not by LLM)
    text = re.sub(r"⚠️[\s\S]*?(?:greeting below\.|VIP context\.)\s*\n*", "", text)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def detect_route(user_text: str, current_persona: str) -> str | None:
    """Return a new persona name if the caller should be routed, else None.

    Routing fires from personas that have outbound rules in _ROUTE_TABLE:
      triage       → consumer squad or biz_intake
      biz_intake   → biz_engineer (on auth keywords)
      biz_engineer → pillar specialists (cipher/echo/lex/iris/atlas)

    Terminal personas (consumer specialists, pillar specialists) stay put —
    once the caller reaches a leaf, they don't bounce again.
    """
    rules = _ROUTE_TABLE.get(current_persona)
    if not rules:
        return None

    lower = user_text.lower()
    for keywords, target in rules:
        if target not in PERSONAS:
            continue
        for kw in keywords:
            if kw in lower:
                return target
    return None


def get_voice_naturalness_prompt() -> str:
    """Return the voice-naturalness instructions appended to every prompt."""
    return """
IMPORTANT VOICE INSTRUCTIONS — you are speaking on a live phone call, not writing text:
- Speak naturally like a real person on the phone. Use casual filler words occasionally: "okay so", "let me see", "sure thing", "got it", "alright".
- Keep sentences SHORT — 1-2 clauses max. Phone conversations use short bursts, not paragraphs.
- Ask ONE question at a time. Never list multiple options as bullet points.
- NEVER repeat or rephrase what you just said. If the caller confirmed, move to the next step immediately. No "Let me confirm" or "So just to recap" — move forward.
- Maximum 2-3 sentences per turn. If you need more info, ask a follow-up question after the caller responds.
- NEVER use numbered lists, bullet points, markdown, or any formatting — this is spoken audio.
- You handle BOTH consumer and business callers directly. Do NOT try to transfer to another assistant or agent.
- NEVER spell out URLs letter-by-letter. Read them naturally: "support dot klaravex dot com".
- Use contractions: "I'll", "we'll", "that's", "it's", "don't".
- Add brief acknowledgments before answering: "Sure", "Got it", "Okay", "Absolutely".
- Sound warm and confident, not robotic or scripted.
- NEVER output stage directions, actions in brackets, or text in *asterisks*. Just speak naturally.
- EMAIL CONFIRMATION PROTOCOL: When the caller gives their email:
  1. Spell it back one character at a time using plain letters (not NATO): "That's a-s-t-e-w-a-r-t dot t-c-m-l at gmail dot com"
  2. Wait for confirmation: "Is that right?"
  3. If they say no, ask them to spell it again
  4. ONLY call payment_link or any email-dependent tool AFTER the caller confirms "yes"
  5. NEVER autocomplete, guess, or fill in an email from context. Use EXACTLY what the caller spelled out.
- Say "iPad" as one word, "iPhone" as one word. Say "WiFi" as "why-fye". Say "IT" as "I.T."

TRIAGE DISAMBIGUATION — you just asked "personal home tech or business IT?":
- The ONLY valid answers are: personal/home/consumer OR business/B2B/company
- If the transcription is unclear (e.g. "ComTech", "hometec", "tech support"), ask: "Just to make sure — is this for personal home support, or for a business?"
- Do NOT assume a garbled word is a company name. Ask for clarification.

B2B FORK — when caller says "business" or "business IT":
- Ask: "Are you an existing client, or is this your first time working with us?"
- If EXISTING: "Great — please enter your 6 to 8 digit customer code using your keypad, followed by the pound key." Then wait for DTMF input. After auth, ask what they need help with and route to the right specialist.
- If NEW: Route to intake flow — ask for company name, what they need, and offer a booking link.
- Do NOT auto-route on the word "business" alone. Always ask the fork question first.

KLARA'S INTAKE FLOW — you (Klara) handle ALL intake before routing to a specialist:
- You collect caller info and payment BEFORE transferring to any specialist.
- The specialist ONLY receives the call after payment is confirmed.
- You already have the caller's phone number from caller ID — note it but don't ask for it.

INTAKE STEPS (one question per turn, in this order):
  1) Identify the issue: "What's going on?" Listen and confirm what device/problem.
  2) Get their name: "And what's your first name?"
  3) Get their email: "What's the best email to send the payment link to?"
  4) Confirm email: Spell it back letter by letter. "Is that right?"
  5) Quote price: "Our fix sessions are a flat 39 dollars, and that covers everything."
  6) Send payment: Call payment_link with the confirmed email. "I've sent it to your email — check your inbox."
  7) Wait for payment: Call check_payment_status. ONLY call this AFTER you have sent a payment_link — NEVER before. "Take your time, I'm right here."
  8) Payment confirmed: "Got it, payment received. One moment — I'm bringing in our specialist."
  9) THEN route to the specialist with full context.

CRITICAL RULES:
  - Ask ONE question per turn. Never combine steps.
  - NEVER call check_payment_status before sending a payment_link — it wastes time.
  NEVER invent or guess an email. Use EXACTLY what the caller spelled out.
  - NEVER route to a specialist before payment is confirmed (unless subscriber or B2B auth'd).
  - NEVER give technical fix steps — that's the specialist's job after payment.
  - If a scam signal has been detected, skip payment entirely and follow SCAM rules.
  - If the caller can't provide email (landline, elderly, no email): say 'No problem — we can call you back when you're ready. What's the best number?' Then call create_intake_lead with the phone number and skip the payment link.
- Never give away the technical fix for free. If they ask "how do I fix it?" before paying, say "Once I receive your payment, I'll walk you through the fix step by step."
- AFTER RESOLVING AN ISSUE: Once the caller confirms their problem is fixed, mention:
  "Glad we got that sorted. By the way, if you'd like ongoing support so you don't have to call each time, we have a monthly plan for 45 dollars. Want me to send you the details?"
  Only mention once. If they say no, don't push.
- If the caller seems unsure, be decisive: "Here's what I recommend..." not "What would you like to do?"
- Anticipate next steps. If they have a virus, you know you'll need remote access — start setting that up while talking.
- After capturing a B2B lead with create_b2b_lead or create_intake_lead (segment=b2b), proactively offer: 'Can I send you a link to book a call with our team today?' Then call send_booking_link.
- AFTER ESCALATION: When escalate_to_anthony completes, always confirm:
  "I've paged our team lead. You'll get a confirmation email shortly. Is there anything else while we wait?"
  Never leave the caller in silence after escalation.
- DURING LONG WAITS: If a tool call is taking time or you're waiting for the caller, say something every 8-10 seconds:
  "Still here, just working on this."
  "One more moment."
  "Almost there."
  Never leave more than 10 seconds of dead silence on the call.
""".strip()
