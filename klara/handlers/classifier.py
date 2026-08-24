"""
Klaravex Ticket Classifier — unified intent tagger for all inbound channels.

Classifies inbound text into intent + severity using fast keyword matching,
with Claude Haiku fallback when confidence is below the threshold.

Usage:
    from klara.handlers.classifier import classify_intent, ESCALATE_INTENTS

    result = classify_intent("my computer won't turn on")
    # {"intent": "hardware_failure", "severity": "P2",
    #  "channel_hint": "phone", "keywords": ["won't turn on"]}

No new pip dependencies required — uses the anthropic package already present.
"""

import logging
import os
import re
from typing import Any

log = logging.getLogger("klaravex.classifier")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Intent taxonomy
# ---------------------------------------------------------------------------

INTENT_SEVERITY: dict[str, str] = {
    "security_incident": "P1",
    "legal_threat":      "P1",
    "refund_request":    "P1",
    "hardware_failure":  "P2",
    "network_issue":     "P2",
    "tech_support":      "P3",
    "password_reset":    "P3",
    "billing_question":  "P4",
    "general_inquiry":   "P4",
    "compliment":        "P4",
    "unknown":           "P4",
}

# Intents that must always be escalated — AI never handles these.
ESCALATE_INTENTS: set[str] = {"security_incident", "legal_threat", "refund_request"}

# Channel hint — preferred follow-up channel per intent.
INTENT_CHANNEL_HINT: dict[str, str] = {
    "security_incident": "phone",
    "legal_threat":      "email",
    "refund_request":    "email",
    "hardware_failure":  "phone",
    "network_issue":     "sms",
    "tech_support":      "sms",
    "password_reset":    "sms",
    "billing_question":  "email",
    "general_inquiry":   "email",
    "compliment":        "email",
    "unknown":           "email",
}

# ---------------------------------------------------------------------------
# Keyword map — ordered by priority (high-stakes intents first).
# Keys must match INTENT_SEVERITY keys exactly.
# ---------------------------------------------------------------------------

KEYWORDS: dict[str, list[str]] = {
    "security_incident": [
        "hacked", "hack", "ransomware", "virus", "breach", "breached",
        "unauthorized", "malware", "stolen", "stolen data", "compromised",
        "phishing", "spyware", "data leak", "account takeover",
    ],
    "legal_threat": [
        "lawyer", "lawsuit", "sue", "suing", "legal action", "attorney",
        "court", "litigation", "legal counsel", "cease and desist",
    ],
    "refund_request": [
        "refund", "money back", "charge back", "chargeback", "dispute",
        "cancel and refund", "get my money", "want a refund", "issue a refund",
    ],
    "hardware_failure": [
        "won't turn on", "wont turn on", "not turning on",
        "won't boot", "wont boot", "won't start", "wont start",
        "screen broken", "blue screen", "bsod", "dead", "cracked screen",
        "no power", "physical damage", "dropped", "water damage",
        "won't power on", "wont power on", "doesn't turn on", "doesnt turn on",
    ],
    "network_issue": [
        "wifi", "wi-fi", "internet", "vpn", "no connection", "can't connect",
        "network", "ethernet", "no internet", "connection dropped",
        "slow internet", "offline", "not connecting",
    ],
    "password_reset": [
        "password", "locked out", "can't log in", "can't login", "reset",
        "forgot password", "lost password", "account locked", "sign in",
        "access denied", "authentication",
    ],
    "billing_question": [
        "invoice", "charge", "billing", "payment", "how much", "price",
        "cost", "fee", "subscription cost", "my bill",
        "overcharged", "double charged",
    ],
    "compliment": [
        "thank you", "thanks", "great service", "amazing", "excellent",
        "love it", "fantastic", "wonderful", "well done", "happy with",
        "pleased", "satisfied", "impressed",
    ],
    "general_inquiry": [
        "pricing", "services", "onboarding", "how do i sign up", "sign up",
        "what do you offer", "plans", "tiers", "what is klaravex",
        "how does it work", "do you offer", "interested in",
    ],
}

# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _keyword_match(text: str) -> tuple[str, float, list[str]]:
    """
    Scan text against KEYWORDS in priority order.

    Returns (intent, confidence, matched_keywords).
    Confidence is 0.9 for a match (heuristic), 0.0 for no match.
    Priority order mirrors KEYWORDS dict insertion order — high-stakes first.
    """
    norm = _normalise(text)
    for intent, kws in KEYWORDS.items():
        matched = [kw for kw in kws if kw in norm]
        if matched:
            # Multi-keyword matches earn higher confidence.
            confidence = min(0.9 + 0.02 * (len(matched) - 1), 0.99)
            return intent, confidence, matched
    return "unknown", 0.0, []


# ---------------------------------------------------------------------------
# Claude Haiku fallback
# ---------------------------------------------------------------------------

_HAIKU_INTENTS = list(INTENT_SEVERITY.keys())
_HAIKU_INTENTS_STR = "\n".join(f"  - {i}" for i in _HAIKU_INTENTS)

_HAIKU_PROMPT = """You are a triage classifier for an IT managed-services company.

Classify the following customer message into exactly ONE of these intents:
{intents}

Rules:
- Reply with only the intent label, nothing else.
- If none fit well, reply: unknown

Message:
{message}"""


def _classify_with_haiku(text: str) -> tuple[str, float, list[str]]:
    """
    Fall back to Claude Haiku when keyword confidence is below threshold.
    Returns (intent, confidence, keywords=[]).
    Returns ("unknown", 0.5, []) on any error.
    """
    if not ANTHROPIC_API_KEY:
        log.warning("ANTHROPIC_API_KEY not set; haiku fallback unavailable")
        return "unknown", 0.5, []

    try:
        import anthropic  # already in requirements
        _gateway = getattr(__import__('settings').settings, 'litellm_base_url', 'http://127.0.0.1:8090')
        client = anthropic.Anthropic(api_key="unused", base_url=_gateway)
        message = client.messages.create(
            model="anthropic/nvidia_nim/deepseek-ai/deepseek-v4-flash-0731",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": _HAIKU_PROMPT.format(
                    intents=_HAIKU_INTENTS_STR,
                    message=text[:800],
                ),
            }],
        )
        raw = message.content[0].text.strip().lower().replace("-", "_")
        # Accept only known intents.
        intent = raw if raw in INTENT_SEVERITY else "unknown"
        confidence = 0.8 if intent != "unknown" else 0.5
        return intent, confidence, []
    except Exception as exc:
        log.warning("haiku classification failed: %s", exc)
        return "unknown", 0.5, []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.7


def classify_intent(text: str) -> dict[str, Any]:
    """
    Classify inbound text into intent + severity.

    Returns a dict with keys:
        intent       str   — one of INTENT_SEVERITY keys
        severity     str   — P1..P4
        channel_hint str   — preferred follow-up channel
        keywords     list  — matched keyword strings (empty for Haiku path)
        confidence   float — 0.0–1.0
        method       str   — "keyword" | "haiku" | "fallback"
    """
    intent, confidence, keywords = _keyword_match(text)

    if confidence >= CONFIDENCE_THRESHOLD:
        method = "keyword"
    else:
        log.debug(
            "keyword confidence %.2f < %.2f, falling back to Haiku for: %r",
            confidence,
            CONFIDENCE_THRESHOLD,
            text[:80],
        )
        intent, confidence, keywords = _classify_with_haiku(text)
        method = "haiku" if confidence >= CONFIDENCE_THRESHOLD else "fallback"

    severity = INTENT_SEVERITY.get(intent, "P4")
    channel_hint = INTENT_CHANNEL_HINT.get(intent, "email")

    return {
        "intent":       intent,
        "severity":     severity,
        "channel_hint": channel_hint,
        "keywords":     keywords,
        "confidence":   round(confidence, 3),
        "method":       method,
    }
