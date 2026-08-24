"""
Klaravex Voice Pipeline — replaces Vapi with fully local voice AI.

Architecture:
  Twilio Media Stream (mulaw 8kHz) → this server → whisper STT → LLM → klara TTS → Twilio

v3: sentence-split TTS, LLM streaming, filler audio, tool calling, VIP gate.

Runs on rig, public access via USA VM Caddy reverse proxy.
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import json
import logging
import os
import re
import struct
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
from datetime import datetime, timezone, timedelta

from tools_registry import TOOL_DEFINITIONS, execute_tool, check_vip, _STUB_RESPONSES
from prompt_router import load_persona, detect_route, get_voice_for_persona, get_voice_naturalness_prompt, PERSONAS
import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("voice-pipeline")

# ── Config ──────────────────────────────────────────────────────────────────
HOST = os.getenv("VOICE_HOST", "0.0.0.0")
PORT = int(os.getenv("VOICE_PORT", "8440"))
PUBLIC_URL = os.getenv("VOICE_PUBLIC_URL", "wss://voice.klaravex.com")

# Backend services (rig via Tailscale)
WHISPER_URL = os.getenv("WHISPER_URL", "http://100.75.10.114:8430")
LLM_URL = os.getenv("LLM_URL", "http://100.75.10.114:8000")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-coder")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
TTS_URL = os.getenv("TTS_URL", "http://100.75.10.114:8420")
TTS_SECRET = os.getenv("TTS_SECRET", "")
TTS_VOICE = os.getenv("TTS_VOICE", "klara-en")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "24000"))  # Chatterbox needs 24kHz, pipeline downsamples to 8kHz for Twilio

# System prompt
SYSTEM_PROMPT_PATH = os.getenv(
    "SYSTEM_PROMPT_PATH",
    "/home/anthony/klaravex/infra/vapi-prompts/triage-en.md"
)

# Cloud fallback keys
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

# Twilio audio: mulaw 8kHz mono
TWILIO_SAMPLE_RATE = 8000
WHISPER_SAMPLE_RATE = 16000

# Turn detection
SILENCE_THRESHOLD = 500
SILENCE_DURATION_MS = 900    # 900ms silence = turn done
MIN_SPEECH_DURATION_MS = 350
BARGE_IN_THRESHOLD = 650     # lower than SILENCE_THRESHOLD * 2 for easier barge-in

# Chunk timing — send full audio to Twilio, let it buffer internally
CHUNK_SIZE = 640  # 80ms at 8kHz mulaw
CHUNK_INTERVAL = 0.0  # no pacing — Twilio handles buffering

VAPI_SHARED_SECRET = os.getenv("VAPI_SHARED_SECRET", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
VOICE_API_SECRET = os.getenv("VOICE_API_SECRET", VAPI_SHARED_SECRET)  # reuse vapi secret


def verify_voice_api_secret(request: Request) -> bool:
    """Check Authorization header for the voice API secret."""
    if not VOICE_API_SECRET:
        return False
    auth = request.headers.get("Authorization", "")
    return auth == f"Bearer {VOICE_API_SECRET}"

FIRST_MESSAGE = os.getenv(
    "FIRST_MESSAGE",
    "Hi, you've reached Klaravex. This is Klara, your A.I. coordinator. "
    "This call may be recorded for quality and training purposes. "
    "Are you calling about personal home tech support, or business I.T. support?"
)

AFTER_HOURS_GREETING = (
    "You've reached Klaravex after hours. Our team isn't available live right now, "
    "but I can take your information so the right person gets back to you first thing. "
    "What's going on, and what's the best way to reach you?"
)


def is_business_hours() -> bool:
    """Check if current time is within business hours (9am-6pm ET, Mon-Fri)."""
    et = timezone(timedelta(hours=-5))  # Eastern Time
    now = datetime.now(et)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    return 9 <= now.hour < 18


async def lookup_caller(phone_number: str) -> dict | None:
    """Look up a caller by phone number from the Klaravex API. Returns caller dict or None."""
    if not phone_number or not VAPI_SHARED_SECRET:
        return None
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.post(
                "https://api.klaravex.com/api/v1/vapi/lookup_client",
                json={"caller_phone": phone_number},
                headers={
                    "x-vapi-secret": VAPI_SHARED_SECRET,
                    "Content-Type": "application/json",
                },
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return data
    except Exception as e:
        log.warning(f"Caller lookup failed for {phone_number}: {e}")
    return None


def load_system_prompt(persona: str = "triage") -> str:
    """Load system prompt for a persona, with voice naturalness appended."""
    try:
        text = load_persona(persona)
    except (KeyError, FileNotFoundError):
        log.warning(f"Persona '{persona}' not found, falling back to triage")
        try:
            text = load_persona("triage")
        except Exception:
            text = "You are Klara, an AI tech support assistant for Klaravex."

    # Strip transfer/VIP references (handled by pipeline, not LLM)
    lines = text.split("\n")
    lines = [l for l in lines if not any(k in l for k in
             ["vapi_vip_access", "transfer_to_specialist", "is_vip",
              "VIP SILENT GATE", "VIP backend", "VIP lookup", "VIP caller",
              "route_to_assistant", "VIP name", "transfer_to_biz",
              "biz_intake", "transfer to the"])]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text + "\n\n" + get_voice_naturalness_prompt()


# ── Sentence splitter ───────────────────────────────────────────────────────

SENTENCE_END = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')

def split_sentences(text: str) -> list[str]:
    """Split text into sentences for incremental TTS."""
    parts = SENTENCE_END.split(text)
    sentences = [s.strip() for s in parts if s.strip()]
    # Merge very short fragments with previous sentence
    merged = []
    for s in sentences:
        if merged and len(s) < 15:
            merged[-1] = merged[-1] + " " + s
        else:
            merged.append(s)
    return merged if merged else [text]


@dataclass
class CallSession:
    call_sid: str
    stream_sid: str = ""
    messages: list = field(default_factory=list)
    audio_buffer: bytearray = field(default_factory=bytearray)
    silence_start: float = 0.0
    is_speaking: bool = False
    speech_start: float = 0.0
    bot_speaking: bool = False
    bot_audio_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancelled: bool = False
    active: bool = True
    processing_turn: bool = False  # lock to prevent overlapping turns
    current_persona: str = "triage"
    current_voice: str = "klara-en"  # only triage uses klara; specialists use chicago-en
    turn_count: int = 0
    frustration_score: float = 0.0  # 0-1 scale
    elderly_mode: bool = False
    avg_speech_rate: float = 0.0  # words per second estimate
    frustration_streak: int = 0  # consecutive turns with frustration_score > 0.7
    caller_phone: str = ""
    caller_info: dict = field(default_factory=dict)
    transcript: list = field(default_factory=list)
    dtmf_buffer: str = ""
    dtmf_timeout: float = 0.0
    filler_index: int = 0
    is_subscriber: bool = False
    is_spanish: bool = False
    pending_route: str = ""  # specialist to route to after payment
    _ws: WebSocket | None = None

    def reset_audio(self):
        self.audio_buffer.clear()
        self.is_speaking = False
        self.silence_start = 0.0
        self.speech_start = 0.0


# ── Caller state analysis ─────────────────────────────────────────────────

FRUSTRATION_PHRASES = [
    "already told you", "not working", "still broken", "frustrated",
    "ridiculous", "come on", "this is terrible", "still not",
    "doesn't work", "not helping", "waste of time", "useless",
    "speak to a human", "talk to someone", "real person",
    "you already asked", "i just said", "are you listening",
]

ELDERLY_HESITATION_PHRASES = [
    "the blue one", "i don't know what that means", "what's a",
    "what is a", "which button", "i'm not sure what",
    "the thing on the", "my grandson", "my son set it up",
    "i can't find", "where is the", "the little box",
]

TRANSITION_MESSAGES = {
    "windows": "One moment — I'm bringing in our Windows specialist. They'll already know your name and what we're working on. Please hold.",
    "apple": "One moment — I'm bringing in our Apple specialist. They'll already know your name and what we're working on. Please hold.",
    "mobile": "One moment — I'm bringing in our mobile device specialist. They'll already know your name and what we're working on. Please hold.",
    "smart_home": "One moment — I'm bringing in our smart home and network specialist. They'll already know your name and what we're working on. Please hold.",
    "identity": "One moment — I'm bringing in our identity and scam recovery specialist. They'll already know your name and what we're working on. Please hold.",
    "biz_intake": "One moment — I'm bringing in our business intake specialist. They'll already know your name and what we're working on. Please hold.",
    
    "cipher": "One moment — I'm bringing in our security specialist. They'll already know your name and what we're working on. Please hold.",
    "echo": "One moment — I'm bringing in our Microsoft 365 and cloud specialist. They'll already know your name and what we're working on. Please hold.",
    "lex": "One moment — I'm bringing in our regulatory readiness specialist. They'll already know your name and what we're working on. Please hold.",
    "iris": "One moment — I'm bringing in our AI adoption specialist. They'll already know your name and what we're working on. Please hold.",
    "atlas": "One moment — I'm bringing in our strategy specialist. They'll already know your name and what we're working on. Please hold.",
}


def analyze_caller_state(
    session: CallSession,
    stt_text: str,
    speech_duration_ms: float,
    rms_avg: float,
) -> None:
    """Analyze caller speech for frustration signals and elderly indicators.

    Updates session.frustration_score, session.elderly_mode, and injects
    system messages into the conversation when thresholds are crossed.
    """
    text_lower = stt_text.lower()
    word_count = len(stt_text.split())

    # ── Speech rate ──
    if speech_duration_ms > 0:
        speech_rate = word_count / (speech_duration_ms / 1000.0)
        # Exponential moving average over turns
        if session.avg_speech_rate == 0.0:
            session.avg_speech_rate = speech_rate
        else:
            session.avg_speech_rate = 0.6 * session.avg_speech_rate + 0.4 * speech_rate
    else:
        speech_rate = 0.0

    # ── Frustration detection ──
    frustration_hit = any(phrase in text_lower for phrase in FRUSTRATION_PHRASES)
    if frustration_hit:
        session.frustration_score = min(1.0, session.frustration_score + 0.15)
    else:
        session.frustration_score = max(0.0, session.frustration_score - 0.05)

    # Track consecutive high-frustration turns
    if session.frustration_score > 0.7:
        session.frustration_streak += 1
    else:
        session.frustration_streak = 0

    if session.frustration_streak >= 3:
        session.messages.append({
            "role": "system",
            "content": (
                "ALERT: Caller is frustrated. Be extra empathetic, apologize, "
                "and offer to escalate to a human."
            ),
        })
        log.info(
            f"[{session.call_sid[:8]}] Frustration alert: "
            f"score={session.frustration_score:.2f}, streak={session.frustration_streak}"
        )

    # ── Elderly mode detection ──
    if not session.elderly_mode and session.turn_count > 4:
        elderly_phrase_hit = any(
            phrase in text_lower for phrase in ELDERLY_HESITATION_PHRASES
        )
        # Exclude email/spelling turns — naturally slow, not elderly
        is_spelling = any(c in text_lower for c in ["@", "dot com", "gmail", "yahoo", "outlook", "hotmail"])
        slow_speech = session.avg_speech_rate < 1.0 and session.avg_speech_rate > 0 and not is_spelling
        short_response = word_count <= 3

        if elderly_phrase_hit and (slow_speech or short_response):
            session.elderly_mode = True
            session.messages.append({
                "role": "system",
                "content": (
                    "ELDERLY CALLER DETECTED: Use simpler language, shorter "
                    "sentences, more patience. Say 'internet box' not 'router'. "
                    "Give one step at a time. Be warm and reassuring."
                ),
            })
            log.info(
                f"[{session.call_sid[:8]}] Elderly mode activated: "
                f"speech_rate={session.avg_speech_rate:.2f} w/s"
            )

    log.debug(
        f"[{session.call_sid[:8]}] Caller state: "
        f"frustration={session.frustration_score:.2f}, "
        f"speech_rate={session.avg_speech_rate:.2f}, "
        f"elderly={session.elderly_mode}, turn={session.turn_count}"
    )


# ── Audio conversion ────────────────────────────────────────────────────────

def mulaw_to_pcm16(mulaw_bytes: bytes) -> bytes:
    return audioop.ulaw2lin(mulaw_bytes, 2)

def pcm16_to_mulaw(pcm16_bytes: bytes) -> bytes:
    return audioop.lin2ulaw(pcm16_bytes, 2)

def resample_8k_to_16k(pcm16_8k: bytes) -> bytes:
    state = None
    resampled, state = audioop.ratecv(pcm16_8k, 2, 1, 8000, 16000, state)
    return resampled

def resample_to_8k(pcm16_bytes: bytes, source_rate: int) -> bytes:
    if source_rate == TWILIO_SAMPLE_RATE:
        return pcm16_bytes
    state = None
    resampled, state = audioop.ratecv(
        pcm16_bytes, 2, 1, source_rate, TWILIO_SAMPLE_RATE, state
    )
    return resampled

def compute_rms(pcm16_bytes: bytes) -> int:
    if len(pcm16_bytes) < 2:
        return 0
    return audioop.rms(pcm16_bytes, 2)


# ── Filler audio ────────────────────────────────────────────────────────────

def generate_filler_audio() -> bytes:
    """Generate a soft 'hmm' sound — warm tone with harmonics.
    300ms of a 200Hz fundamental + harmonics (400Hz, 600Hz) at low volume,
    with smooth fade in/out for a natural feel.
    """
    duration = 0.3  # 300ms
    sr = TWILIO_SAMPLE_RATE
    n = int(sr * duration)
    t = np.arange(n, dtype=np.float32) / sr
    # Smooth fade in/out envelope
    envelope = np.sin(np.pi * t / duration)
    # Warm tone: fundamental + harmonics for a natural "hmm"
    tone = (
        np.sin(2 * np.pi * 200 * t) * 1.0 +       # fundamental
        np.sin(2 * np.pi * 400 * t) * 0.5 +        # 2nd harmonic
        np.sin(2 * np.pi * 600 * t) * 0.25          # 3rd harmonic
    ) * envelope * 400  # low amplitude
    pcm16 = tone.astype(np.int16).tobytes()
    return pcm16_to_mulaw(pcm16)


def generate_hold_music() -> bytes:
    """Generate a gentle arpeggio loop for hold music.
    C4(262) -> E4(330) -> G4(392) -> C5(523), each 400ms.
    Total loop ~1.6 seconds at very low volume.
    """
    sr = TWILIO_SAMPLE_RATE
    note_duration = 0.4  # 400ms per note
    frequencies = [262, 330, 392, 523]  # C4, E4, G4, C5
    samples = []
    for freq in frequencies:
        n = int(sr * note_duration)
        t = np.arange(n, dtype=np.float32) / sr
        # Smooth envelope per note
        envelope = np.sin(np.pi * t / note_duration)
        note = np.sin(2 * np.pi * freq * t) * envelope * 300  # very low volume
        samples.append(note)
    pcm16 = np.concatenate(samples).astype(np.int16).tobytes()
    return pcm16_to_mulaw(pcm16)


FILLER_AUDIO = generate_filler_audio()
HOLD_MUSIC = generate_hold_music()

FILLER_PHRASES = [
    "Hmm, let me check on that.",
    "One moment...",
    "Let me see...",
    "Sure, give me just a sec.",
    "Okay, looking into that now.",
]


def generate_breath_pause(duration_ms: int = 150) -> bytes:
    """Generate a brief silence for between-sentence pauses."""
    sr = TWILIO_SAMPLE_RATE
    n = int(sr * duration_ms / 1000)
    silence = np.zeros(n, dtype=np.int16).tobytes()
    return pcm16_to_mulaw(silence)


BREATH_PAUSE = generate_breath_pause(180)  # 180ms pause between sentences


# ── Backend calls (local + cloud fallback) ──────────────────────────────────

# Cache rig health to avoid checking every audio frame
_rig_healthy = True
_rig_last_check = 0.0
RIG_CHECK_INTERVAL = 30  # re-check every 30s


async def check_rig_health() -> bool:
    global _rig_healthy, _rig_last_check
    now = time.time()
    if now - _rig_last_check < RIG_CHECK_INTERVAL:
        return _rig_healthy
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{WHISPER_URL}/health")
            _rig_healthy = r.status_code == 200
    except Exception:
        _rig_healthy = False
    _rig_last_check = now
    if not _rig_healthy:
        log.warning("Rig unreachable — falling back to cloud")
    return _rig_healthy


async def is_rig_up() -> bool:
    return await check_rig_health()


# ── STT ─────────────────────────────────────────────────────────────────────

async def transcribe_local(pcm16_16k: bytes) -> str:
    import tempfile
    import wave

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        with wave.open(f.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(WHISPER_SAMPLE_RATE)
            wf.writeframes(pcm16_16k)
        tmp_path = f.name

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            with open(tmp_path, "rb") as f:
                r = await client.post(
                    f"{WHISPER_URL}/v1/audio/transcriptions",
                    files={"file": ("audio.wav", f, "audio/wav")},
                    data={
                        "model": "whisper-1",
                        "prompt": "Klaravex, Klara, home tech support, business IT support, Mac, iPhone, iPad, Windows, Android, WiFi",
                    },
                )
            if r.status_code == 200:
                data = r.json()
                detected_lang = data.get("language", "en")
                return data.get("text", "").strip(), detected_lang
            log.error(f"Whisper local error: {r.status_code}")
            return "", "en"
    finally:
        os.unlink(tmp_path)


async def transcribe_cloud(pcm16_16k: bytes) -> str:
    """Fallback: Deepgram Nova-3 REST API."""
    if not DEEPGRAM_API_KEY:
        log.error("No DEEPGRAM_API_KEY for cloud fallback")
        return ""
    if len(pcm16_16k) < 3200:  # less than 0.1 seconds — Deepgram returns 400 on tiny chunks
        log.debug("Audio too short for Deepgram, skipping")
        return ""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.deepgram.com/v1/listen?model=nova-3&language=en",
                headers={
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                    "Content-Type": "audio/raw;encoding=linear16;sample_rate=16000;channels=1",
                },
                content=pcm16_16k,
            )
            if r.status_code == 200:
                data = r.json()
                alt = data.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0]
                return alt.get("transcript", "").strip()
            log.error(f"Deepgram error: {r.status_code}")
            return ""
    except Exception as e:
        log.error(f"Deepgram exception: {e}")
        return ""


async def transcribe(pcm16_16k: bytes) -> tuple[str, str]:
    """Returns (text, detected_language)."""
    if await is_rig_up():
        text, lang = await transcribe_local(pcm16_16k)
        if text:
            return text, lang
    cloud_text = await transcribe_cloud(pcm16_16k)
    return cloud_text, "en"  # Deepgram doesn't return language in this path


# ── LLM ─────────────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    """Result from a streaming LLM call — either text content or tool calls."""
    content: str = ""
    tool_calls: list = field(default_factory=list)  # [{id, name, arguments}]


async def _llm_call(url: str, api_key: str, model: str, messages: list[dict],
                     tools: list | None = None) -> LLMResult:
    """Non-streaming LLM call that supports tool calls."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.7,
    }
    if tools:
        payload["tools"] = tools

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{url}/chat/completions", json=payload, headers=headers)
        if r.status_code != 200:
            log.error(f"LLM error ({url}): {r.status_code} {r.text[:200]}")
            return LLMResult(content="I'm sorry, I'm having a technical issue. Could you please try again?")

        data = r.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})

        result = LLMResult(content=msg.get("content", "") or "")

        # Extract tool calls if present
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            result.tool_calls.append({
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "arguments": args,
            })

        return result


async def _llm_stream_from(url: str, api_key: str, model: str, messages: list[dict]):
    """Streaming LLM call for text-only responses (no tool support)."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 150,
        "temperature": 0.7,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream("POST", f"{url}/chat/completions", json=payload, headers=headers) as r:
            if r.status_code != 200:
                error = await r.aread()
                log.error(f"LLM error ({url}): {r.status_code} {error[:200]}")
                yield "I'm sorry, I'm having a technical issue. Could you please try again?"
                return

            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


def _pick_llm():
    """Return (url, api_key, model) for the current best LLM."""
    # 2026-08-16: OpenRouter fallback removed (Anthony canceled OpenRouter).
    # Always the rig LLM; if it is unhealthy, calls fail rather than egressing.
    return f"{LLM_URL}/v1", LLM_API_KEY, LLM_MODEL


async def llm_with_tools(messages: list[dict], session: CallSession) -> str:
    """Call LLM with tool support. Executes tools and re-calls until text response."""
    url, api_key, model = _pick_llm()

    for _ in range(3):  # max 3 tool call rounds
        result = await _llm_call(url, api_key, model, messages, tools=TOOL_DEFINITIONS)

        if not result.tool_calls:
            return result.content

        # Execute each tool call
        for tc in result.tool_calls:
            log.info(f"[{session.call_sid[:8]}] Tool call: {tc['name']}({json.dumps(tc['arguments'])[:100]})")

            # Inject call context
            tc["arguments"].setdefault("call_sid", session.call_sid)

            # Speak filler while executing
            await speak_text(session, "One moment, let me take care of that.")

            tool_result = await execute_tool(tc["name"], tc["arguments"])
            log.info(f"[{session.call_sid[:8]}] Tool result: {tool_result[:100]}")

            # If this was a stub (hallucinated tool like transfer_to_biz_intake),
            # break the tool loop and re-call LLM WITHOUT tools to force a text response.
            # This prevents the LLM from calling the stub in a loop.
            if tc["name"] in _STUB_RESPONSES:
                log.info(f"[{session.call_sid[:8]}] Stub tool '{tc['name']}' hit — breaking tool loop")
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": tool_result})
                result = await _llm_call(url, api_key, model, messages, tools=None)
                return result.content or "How can I help you today?"

            # Payment confirmed → route to pending specialist
            if tc["name"] == "check_payment_status" and '"paid": true' in tool_result.lower():
                if session.pending_route:
                    target = session.pending_route
                    session.pending_route = ""
                    log.info(f"[{session.call_sid[:8]}] Payment confirmed → routing to {target}")
                    transition = TRANSITION_MESSAGES.get(target, "One moment — I'm bringing in a specialist.")
                    await speak_text(session, transition)
                    # Build context for specialist
                    user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
                    context = (f"CALLER CONTEXT: name={session.caller_info.get('name', 'unknown')}, "
                               f"phone={session.caller_phone}, payment=confirmed. "
                               f"Issue: {'; '.join(user_msgs[-3:])}")
                    session.current_persona = target
                    session.current_voice = get_voice_for_persona(target, is_spanish=session.is_spanish)
                    new_prompt = load_system_prompt(target)
                    session.messages[0] = {"role": "system", "content": new_prompt}
                    session.messages.append({"role": "system", "content": context})
                    await speak_text(session, "Hi there, I've got all the details from Klara. Let's get this sorted for you.")

            # B2B auth: successful lookup_client → stay in triage but mark as auth'd
            # Pillar routing happens on the NEXT turn based on what they ask about
            if tc["name"] in ("lookup_client",) and '"trust_level"' in tool_result:
                try:
                    client_data = json.loads(tool_result)
                    if client_data.get("trust_level") in ("full", "verify"):
                        name = client_data.get("name", client_data.get("company", ""))
                        pillars = client_data.get("purchased_pillars", [])
                        log.info(f"[{session.call_sid[:8]}] B2B auth success: {name}, pillars={pillars}")
                        session.caller_info = client_data
                        session.is_subscriber = True
                        session.messages.append({"role": "system", "content":
                            f"AUTHENTICATED B2B CLIENT: {name}. "
                            f"Purchased services: {', '.join(pillars) if pillars else 'unknown'}. "
                            f"Skip payment gate. Ask what they need help with today. "
                            f"Based on their answer, you will be routed to the right specialist."})
                except (json.JSONDecodeError, KeyError):
                    pass

            # Add tool call + result to messages
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": tc["id"], "type": "function",
                                "function": {"name": tc["name"],
                                             "arguments": json.dumps(tc["arguments"])}}],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            })

    return result.content or "I've completed that for you."


async def llm_stream(messages: list[dict]):
    """Stream text-only LLM response (no tools)."""
    url, api_key, model = _pick_llm()
    async for chunk in _llm_stream_from(url, api_key, model, messages):
        yield chunk


# ── TTS ─────────────────────────────────────────────────────────────────────

async def synthesize_local(text: str, voice: str = "") -> bytes:
    headers = {"Content-Type": "application/json"}
    if TTS_SECRET:
        headers["Authorization"] = f"Bearer {TTS_SECRET}"

    payload = {
        "message": {
            "type": "voice-request",
            "text": text,
            "sampleRate": TTS_SAMPLE_RATE,
            "voiceId": voice or TTS_VOICE,
        }
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{TTS_URL}/tts", json=payload, headers=headers)
        if r.status_code == 200:
            return r.content
        log.error(f"TTS local error: {r.status_code}")
        return b""


async def synthesize_cloud(text: str) -> bytes:
    """Fallback: ElevenLabs TTS."""
    if ELEVENLABS_API_KEY:
        try:
            # Use cloned Klara voice on ElevenLabs
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    "https://api.elevenlabs.io/v1/text-to-speech/1uCxP8VNgp8azoCLnZl4",
                    headers={
                        "xi-api-key": ELEVENLABS_API_KEY,
                        "Content-Type": "application/json",
                        "Accept": "audio/pcm",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_turbo_v2_5",
                        "output_format": "pcm_16000",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                    },
                )
                if r.status_code == 200:
                    pcm = r.content
                    # ElevenLabs returns 16kHz — resample to match TTS_SAMPLE_RATE
                    pcm = resample_to_8k(pcm, 16000)
                    return pcm
                log.error(f"ElevenLabs error: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.error(f"ElevenLabs exception: {e}")

    return b""


async def synthesize(text: str, voice: str = "") -> bytes:
    # Local TTS primary (Chatterbox)
    if await is_rig_up():
        result = await synthesize_local(text, voice=voice)
        if result:
            return result
    log.warning("TTS falling back to ElevenLabs cloud voice")
    return await synthesize_cloud(text)


async def queue_audio(session: CallSession, mulaw_bytes: bytes):
    """Queue mulaw audio for sending to Twilio, respecting barge-in."""
    for i in range(0, len(mulaw_bytes), CHUNK_SIZE):
        if session.cancelled:
            session.cancelled = False
            return
        chunk = mulaw_bytes[i:i + CHUNK_SIZE]
        await session.bot_audio_queue.put(chunk)


async def speak_text(session: CallSession, text: str, rate: float = 1.0):
    """Synthesize text and queue the audio for playback.
    rate < 1.0 = slower (more deliberate), > 1.0 = faster (casual).
    """
    if not session.active:
        return
    # Strip bracket/stage-direction text: [Checking...], *sighs*, etc.
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\*.*?\*', '', text)
    text = text.strip()
    if not text:
        return

    tts_pcm = await synthesize(text, voice=session.current_voice if hasattr(session, 'current_voice') else "")
    if not tts_pcm:
        return

    # Apply speech rate by resampling before the final 8kHz conversion
    if rate != 1.0 and tts_pcm:
        samples = np.frombuffer(tts_pcm, dtype=np.int16).astype(np.float32)
        # Stretch/compress by resampling: rate > 1 = faster, < 1 = slower
        new_len = int(len(samples) / rate)
        indices = np.linspace(0, len(samples) - 1, new_len)
        left = indices.astype(int)
        frac = (indices - left).astype(np.float32)
        right = np.minimum(left + 1, len(samples) - 1)
        resampled = samples[left] * (1 - frac) + samples[right] * frac
        tts_pcm = resampled.astype(np.int16).tobytes()

    # Normalize audio to prevent clipping (max 80% of range = no distortion)
    samples = np.frombuffer(tts_pcm, dtype=np.int16).astype(np.float32)
    peak = np.max(np.abs(samples))
    if peak > 26000:  # clipping threshold
        samples = samples * (26000.0 / peak)
        tts_pcm = samples.astype(np.int16).tobytes()

    pcm16_8k = resample_to_8k(tts_pcm, TTS_SAMPLE_RATE)
    mulaw = pcm16_to_mulaw(pcm16_8k)
    await queue_audio(session, mulaw)


# ── Message trimming ───────────────────────────────────────────────────────

def trim_messages(messages: list[dict], max_len: int = 30, keep_recent: int = 20) -> list[dict]:
    """Keep conversation history bounded: system prompt + summary + last N messages."""
    if len(messages) <= max_len:
        return messages
    system_msg = messages[0]
    recent = messages[-keep_recent:]
    summary = {
        "role": "system",
        "content": (
            "Earlier in this call, the conversation covered the topics above. "
            "Focus on the most recent messages."
        ),
    }
    return [system_msg, summary] + recent


# ── Pipeline ────────────────────────────────────────────────────────────────

async def process_turn(session: CallSession) -> None:
    """Process a complete caller turn with tool-calling LLM + sentence-split TTS."""
    if not session.active or not session.audio_buffer:
        return
    session.processing_turn = True
    session.cancelled = False  # reset barge-in flag from greeting
    session.turn_count += 1

    audio_bytes = bytes(session.audio_buffer)
    # Calculate speech duration from audio length before resetting
    # mulaw is 8kHz 1 byte per sample
    speech_duration_ms = len(audio_bytes) / TWILIO_SAMPLE_RATE * 1000.0
    session.reset_audio()

    # 1. Transcribe
    pcm16_8k = mulaw_to_pcm16(audio_bytes)
    pcm16_16k = resample_8k_to_16k(pcm16_8k)
    rms_avg = compute_rms(pcm16_8k)

    if len(pcm16_16k) < WHISPER_SAMPLE_RATE * 2:  # less than 1 second of 16-bit audio
        log.info(f"[{session.call_sid[:8]}] Audio too short, skipping")
        return

    t0 = time.time()
    text, detected_lang = await transcribe(pcm16_16k)
    stt_ms = (time.time() - t0) * 1000
    log.info(f"[{session.call_sid[:8]}] STT ({stt_ms:.0f}ms, lang={detected_lang}): '{text}'")

    if not text or len(text.strip()) < 2:
        session.processing_turn = False
        return

    # Auto-detect Spanish — only on caller speech (not bot echo), require keywords too
    if (detected_lang == "es" and session.current_persona == "triage"
            and session.turn_count < 3 and len(text.split()) >= 3):
        # Double-check with keyword detection — whisper lang detection can be noisy
        spanish_words = ["hola", "necesito", "ayuda", "problema", "español", "no hablo", "computadora"]
        if any(w in text.lower() for w in spanish_words):
            log.info(f"[{session.call_sid[:8]}] Spanish confirmed — switching to triage_es")
            session.is_spanish = True
            session.current_persona = "triage_es"
            session.current_voice = get_voice_for_persona("triage_es", is_spanish=True)
            new_prompt = load_system_prompt("triage_es")
            session.messages[0] = {"role": "system", "content": new_prompt}

    # Analyze caller emotional state and speech patterns
    analyze_caller_state(session, text, speech_duration_ms, rms_avg)

    session.messages.append({"role": "user", "content": text})
    session.transcript.append({"role": "user", "text": text, "timestamp": time.time()})

    # 2. Check if we should route to a specialist persona
    new_persona = detect_route(text, session.current_persona)
    if new_persona:
        if new_persona == "triage_es":
            # Language switch happens immediately
            log.info(f"[{session.call_sid[:8]}] Language switch: → triage_es")
            session.is_spanish = True
            session.current_persona = "triage_es"
            session.current_voice = get_voice_for_persona("triage_es", is_spanish=True)
            new_prompt = load_system_prompt("triage_es")
            session.messages[0] = {"role": "system", "content": new_prompt}
        elif new_persona in ("biz_intake",):
            # B2B intake routes immediately (no payment gate for intake)
            log.info(f"[{session.call_sid[:8]}] Routing: → biz_intake")
            session.current_persona = new_persona
            session.current_voice = get_voice_for_persona(new_persona, is_spanish=session.is_spanish)
            new_prompt = load_system_prompt(new_persona)
            session.messages[0] = {"role": "system", "content": new_prompt}
        else:
            # Consumer specialist — Klara notes the target but does NOT route yet
            # Routing happens after payment via the payment confirmation handler
            log.info(f"[{session.call_sid[:8]}] Target detected: {new_persona} (pending payment)")
            session.pending_route = new_persona
            session.messages.append({"role": "system", "content":
                f"DETECTED SPECIALIST NEEDED: {new_persona}. "
                f"Complete the intake flow (name, email, payment) FIRST. "
                f"After payment is confirmed, say 'One moment' and the system will route to the specialist."})

        # 2b. Consumer subscriber check — skip payment gate for active subscribers
        CONSUMER_SPECIALISTS = {"windows", "apple", "mobile", "smart_home", "identity"}
        if new_persona in CONSUMER_SPECIALISTS and session.caller_phone and not session.is_subscriber:
            try:
                caller_data = session.caller_info or await lookup_caller(session.caller_phone)
                if caller_data:
                    session.caller_info = caller_data
                    plan = caller_data.get("subscription") or caller_data.get("plan")
                    if plan:
                        session.is_subscriber = True
                        session.messages.append({
                            "role": "system",
                            "content": (
                                "SUBSCRIBER: This caller has an active plan. "
                                "Skip the payment gate — provide support directly."
                            ),
                        })
                        log.info(
                            f"[{session.call_sid[:8]}] Subscriber confirmed: "
                            f"plan={plan}, skipping payment gate"
                        )
            except Exception as e:
                log.warning(f"[{session.call_sid[:8]}] Subscriber check failed (fail-open): {e}")

    # 3. No filler — just set bot_speaking and let the LLM respond directly
    session.bot_speaking = True

    # 3b. Trim message history to prevent unbounded growth
    session.messages = trim_messages(session.messages)

    # 3c. LLM with tool support — non-streaming call first to check for tools
    t0 = time.time()
    response = await llm_with_tools(session.messages, session)
    llm_ms = (time.time() - t0) * 1000
    log.info(f"[{session.call_sid[:8]}] LLM ({llm_ms:.0f}ms): '{response[:100]}'")

    if not response or not session.active:
        session.bot_speaking = False
        return

    # 4. Sentence-split TTS
    full_response = response
    sentences = split_sentences(response)

    tts_rate = 1.0  # don't change rate — pitch-shifts the voice
    for i, sent in enumerate(sentences):
        if session.cancelled or not session.active:
            break
        t1 = time.time()
        await speak_text(session, sent, rate=tts_rate)
        # Breath pause between sentences (not after the last one)
        if i < len(sentences) - 1:
            await queue_audio(session, BREATH_PAUSE)
        tts_ms = (time.time() - t1) * 1000
        log.info(f"[{session.call_sid[:8]}] TTS sentence ({tts_ms:.0f}ms): '{sent[:60]}'")

    session.bot_speaking = False
    session.processing_turn = False
    session.messages.append({"role": "assistant", "content": full_response})
    session.transcript.append({"role": "assistant", "text": full_response, "timestamp": time.time()})

    total_ms = (time.time() - t0) * 1000
    log.info(f"[{session.call_sid[:8]}] Turn complete ({total_ms:.0f}ms total)")


async def process_dtmf_turn(session: CallSession) -> None:
    """Process a DTMF-injected message (no STT needed — message already appended)."""
    if not session.active:
        return
    session.processing_turn = True
    session.reset_audio()

    # Speak natural filler phrase while LLM thinks
    session.bot_speaking = True
    t0 = time.time()
    response = await llm_with_tools(session.messages, session)
    llm_ms = (time.time() - t0) * 1000
    log.info(f"[{session.call_sid[:8]}] LLM ({llm_ms:.0f}ms): '{response[:100]}'")

    if not response or not session.active:
        session.bot_speaking = False
        session.processing_turn = False
        return

    full_response = response
    sentences = split_sentences(response)

    for i, sent in enumerate(sentences):
        if session.cancelled or not session.active:
            break
        t1 = time.time()
        await speak_text(session, sent)
        if i < len(sentences) - 1:
            await queue_audio(session, BREATH_PAUSE)
        tts_ms = (time.time() - t1) * 1000
        log.info(f"[{session.call_sid[:8]}] TTS sentence ({tts_ms:.0f}ms): '{sent[:60]}'")

    session.bot_speaking = False
    session.processing_turn = False
    session.messages.append({"role": "assistant", "content": full_response})

    total_ms = (time.time() - t0) * 1000
    log.info(f"[{session.call_sid[:8]}] DTMF turn complete ({total_ms:.0f}ms total)")


# ── Post-call actions ──────────────────────────────────────────────────────

async def post_call_actions(session: CallSession) -> None:
    """Save transcript and send follow-up SMS after call ends."""
    # 1. Save transcript
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "https://api.klaravex.com/api/v1/internal/call-transcript",
                json={
                    "call_sid": session.call_sid,
                    "caller_phone": session.caller_phone,
                    "transcript": session.transcript,
                    "persona": session.current_persona,
                    "turn_count": session.turn_count,
                },
                headers={"x-vapi-secret": VAPI_SHARED_SECRET},
            )
    except Exception as e:
        log.warning(f"[{session.call_sid[:8]}] Failed to save transcript: {e}")

    # 2. Send follow-up SMS
    if session.caller_phone and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
                    data={
                        "From": TWILIO_FROM_NUMBER,
                        "To": session.caller_phone,
                        "Body": (
                            "Thanks for calling Klaravex! If you need anything else, "
                            "call us anytime at (424) 348-6010 or visit support.klaravex.com"
                        ),
                    },
                    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                )
        except Exception as e:
            log.warning(f"[{session.call_sid[:8]}] Failed to send follow-up SMS: {e}")


# ── FastAPI app ─────────────────────────────────────────────────────────────

_cached_greeting_audio = b""  # pre-synthesized greeting mulaw
_http_client = None  # shared httpx client with connection pooling


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cached_greeting_audio, _http_client
    _http_client = httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=20))
    log.info("Voice pipeline v2 starting")
    # Pre-synthesize the greeting at startup so first call is instant
    try:
        tts_pcm = await synthesize(FIRST_MESSAGE)
        if tts_pcm:
            pcm16_8k = resample_to_8k(tts_pcm, TTS_SAMPLE_RATE)
            _cached_greeting_audio = pcm16_to_mulaw(pcm16_8k)
            log.info(f"Greeting pre-cached: {len(_cached_greeting_audio)} bytes")
    except Exception as e:
        log.warning(f"Failed to pre-cache greeting: {e}")
    yield
    if _http_client:
        await _http_client.aclose()
    log.info("Voice pipeline shutting down")


app = FastAPI(title="Klaravex Voice Pipeline", lifespan=lifespan)


@app.get("/health")
async def health():
    rig_ok = await check_rig_health()
    return {
        "status": "ok",
        "version": 2,
        "rig_reachable": rig_ok,
        "stt": "up" if rig_ok else "cloud",
        "llm": "up" if rig_ok else "cloud",
        "tts": "up" if rig_ok else "cloud",
    }


@app.post("/voice/incoming")
async def voice_incoming(request: Request):
    """Return TwiML for Twilio — validates Twilio signature."""
    # Twilio signature verification
    if TWILIO_AUTH_TOKEN:
        sig = request.headers.get("X-Twilio-Signature", "")
        if not sig:
            log.warning("Incoming call rejected — no Twilio signature")
            return Response(content="Forbidden", status_code=403)
        # Twilio sends POST with form data — signature covers URL + params
        # For now, verify signature header exists (full validation requires
        # the exact public URL which may differ behind Caddy proxy)

    form = await request.form()
    caller = form.get("From", "")
    ws_url = f"{PUBLIC_URL}/voice/ws"
    twiml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Start>
        <Record recordingStatusCallback="{PUBLIC_URL.replace('wss://', 'https://')}/voice/recording-status" />
    </Start>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="From" value="{caller}" />
        </Stream>
    </Connect>
</Response>'''
    return Response(content=twiml, media_type="application/xml")


@app.post("/voice/outbound")
async def voice_outbound(request: Request):
    """Trigger an outbound call. Requires VOICE_API_SECRET in Authorization header."""
    # Auth check — prevent unauthorized outbound calls
    auth = request.headers.get("Authorization", "")
    if not VOICE_API_SECRET:
        return Response(content='{"error":"API secret not configured"}', status_code=503)
    if auth != f"Bearer {VOICE_API_SECRET}":
        log.warning(f"Outbound call rejected — invalid auth")
        return Response(content='{"error":"unauthorized"}', status_code=401)

    body = await request.json()
    to_number = body.get("to")
    persona = body.get("persona", "triage")

    if not to_number:
        return {"error": "'to' phone number required"}
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return {"error": "Twilio credentials not configured"}

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Calls.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={
                "To": to_number,
                "From": TWILIO_FROM_NUMBER,
                "Url": f"{PUBLIC_URL.replace('wss://', 'https://')}/voice/incoming",
            },
        )
        if r.status_code in (200, 201):
            data = r.json()
            return {"call_sid": data.get("sid"), "status": data.get("status")}
        return {"error": f"Twilio error {r.status_code}: {r.text[:200]}"}


@app.websocket("/voice/ws")
async def voice_websocket(ws: WebSocket):
    # Basic validation — Twilio sends specific headers on Media Stream WebSockets
    # Full IP-range validation is impractical (AWS IPs change), but we verify
    # the stream sends a valid 'start' event with callSid before processing audio
    await ws.accept()
    log.info("Twilio Media Stream connected")

    # Validate first message is a Twilio 'connected' event — reject spoofed connections
    try:
        first_msg = await asyncio.wait_for(ws.receive_text(), timeout=5.0)
        first_data = json.loads(first_msg)
        if first_data.get("event") != "connected":
            log.warning(f"WebSocket rejected — first event was '{first_data.get('event')}', expected 'connected'")
            await ws.close(code=1008, reason="Invalid stream")
            return
        log.info("Twilio stream connected")
    except (asyncio.TimeoutError, json.JSONDecodeError):
        log.warning("WebSocket rejected — no valid connected event within 5s")
        await ws.close(code=1008, reason="Invalid stream")
        return

    session = CallSession(call_sid="unknown", _ws=ws)
    system_prompt = load_system_prompt()
    session.messages = [{"role": "system", "content": system_prompt}]

    # Audio sender — paces chunks at 20ms intervals for smooth playback
    async def send_audio_task():
        last_audio_sent = time.time()
        heartbeat_sent = False
        while True:
            try:
                chunk = await asyncio.wait_for(
                    session.bot_audio_queue.get(), timeout=0.1
                )
                payload = base64.b64encode(chunk).decode("ascii")
                await ws.send_json({
                    "event": "media",
                    "streamSid": session.stream_sid,
                    "media": {"payload": payload},
                })
                # Pace playback — sleep for chunk duration to prevent buffer dump
                if CHUNK_INTERVAL > 0:
                    await asyncio.sleep(CHUNK_INTERVAL)
                last_audio_sent = time.time()
                heartbeat_sent = False
            except asyncio.TimeoutError:
                # Silence heartbeat: if 8+ seconds with no audio while processing
                if (not heartbeat_sent
                        and (session.bot_speaking or session.processing_turn)
                        and (time.time() - last_audio_sent) >= 15.0):
                    heartbeat_sent = True
                    log.info(f"[{session.call_sid[:8]}] Silence heartbeat — reassuring caller")
                    asyncio.create_task(speak_text(session, "Still here, just working on this for you."))
                continue
            except Exception:
                break

    sender_task = asyncio.create_task(send_audio_task())

    # Greeting — play cached audio INSTANTLY, do lookups in background
    async def send_greeting():
        # Play greeting immediately from cache — no waiting for TTS
        session.bot_speaking = True
        if _cached_greeting_audio:
            await queue_audio(session, _cached_greeting_audio)
            greeting = FIRST_MESSAGE
            # Wait for audio to finish playing
            audio_duration = len(_cached_greeting_audio) / TWILIO_SAMPLE_RATE
            await asyncio.sleep(audio_duration)
        else:
            await speak_text(session, FIRST_MESSAGE)
            greeting = FIRST_MESSAGE
        session.bot_speaking = False
        session.messages.append({"role": "assistant", "content": greeting})
        log.info(f"[{session.call_sid[:8]}] Greeting sent")

        # Background lookups — VIP + caller memory (don't block greeting)
        try:
            vip_result = await check_vip(session.caller_phone or "+0", session.call_sid)
            if vip_result.get("is_vip"):
                log.info(f"[{session.call_sid[:8]}] VIP detected")
                session.messages.append({"role": "system", "content": f"VIP CALLER: {vip_result.get('context', '')}"})
        except Exception:
            pass

        try:
            caller = await lookup_caller(session.caller_phone)
            if caller:
                session.caller_info = caller
                name = caller.get("name", "")
                company = caller.get("company", "")
                last_issue = caller.get("last_issue", "")
                log.info(f"[{session.call_sid[:8]}] Returning caller: {name}")
                ctx = f"CALLER CONTEXT: Returning caller, name={name}"
                if company:
                    ctx += f", company={company}"
                if last_issue:
                    ctx += f", last_issue={last_issue}"
                session.messages.append({"role": "system", "content": ctx})
        except Exception:
            pass

    greeting_task = None

    try:
        while True:
            msg = await ws.receive_text()
            data = json.loads(msg)
            event = data.get("event")

            if event == "connected":
                pass  # already validated on connect

            elif event == "start":
                meta = data.get("start", {})
                session.call_sid = meta.get("callSid", "unknown")
                session.stream_sid = meta.get("streamSid", "")
                session.caller_phone = (
                    meta.get("customParameters", {}).get("From", "")
                    or meta.get("customParameters", {}).get("from", "")
                )
                log.info(
                    f"[{session.call_sid[:8]}] Stream started: "
                    f"streamSid={session.stream_sid} caller={session.caller_phone}"
                )
                greeting_task = asyncio.create_task(send_greeting())

            elif event == "media":
                payload = data["media"]["payload"]
                mulaw_bytes = base64.b64decode(payload)
                rms = compute_rms(mulaw_to_pcm16(mulaw_bytes))

                # Barge-in detection
                if session.bot_speaking and rms > BARGE_IN_THRESHOLD:
                    log.info(f"[{session.call_sid[:8]}] Barge-in detected (rms={rms})")
                    session.cancelled = True
                    session.bot_speaking = False
                    # Drain queue
                    while not session.bot_audio_queue.empty():
                        try:
                            session.bot_audio_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    # Tell Twilio to stop playing
                    await ws.send_json({
                        "event": "clear",
                        "streamSid": session.stream_sid,
                    })

                if session.bot_speaking or session.processing_turn:
                    continue
                
                # Debug: log first audio frame received after greeting
                if not hasattr(session, '_first_audio_logged'):
                    session._first_audio_logged = True
                    log.info(f"[{session.call_sid[:8]}] First audio frame: rms={rms}")

                # Turn detection
                if rms > SILENCE_THRESHOLD:
                    if not session.is_speaking:
                        session.is_speaking = True
                        session.speech_start = time.time()
                    session.silence_start = 0.0
                    session.audio_buffer.extend(mulaw_bytes)
                else:
                    if session.is_speaking:
                        session.audio_buffer.extend(mulaw_bytes)  # keep silence in buffer
                        if session.silence_start == 0.0:
                            session.silence_start = time.time()
                        elif (time.time() - session.silence_start) * 1000 > SILENCE_DURATION_MS:
                            speech_duration = (time.time() - session.speech_start) * 1000
                            if speech_duration >= MIN_SPEECH_DURATION_MS and not session.bot_speaking and not session.processing_turn:
                                log.info(
                                    f"[{session.call_sid[:8]}] Turn ended "
                                    f"({speech_duration:.0f}ms speech)"
                                )
                                asyncio.create_task(process_turn(session))
                            else:
                                session.reset_audio()

            elif event == "dtmf":
                digit = data.get("dtmf", {}).get("digit", "")
                if digit:
                    session.dtmf_buffer += digit
                    session.dtmf_timeout = time.time()
                    log.info(f"[{session.call_sid[:8]}] DTMF digit: {digit} (buffer: {session.dtmf_buffer})")
                    if digit == "#" or len(session.dtmf_buffer) >= 8:
                        dtmf_input = session.dtmf_buffer.rstrip("#")
                        session.dtmf_buffer = ""
                        session.dtmf_timeout = 0.0
                        log.info(f"[{session.call_sid[:8]}] DTMF complete: {dtmf_input}")

                        # Emergency code bypass
                        if dtmf_input in ("911", "000", "999"):
                            session.messages.append({"role": "system", "content": "EMERGENCY: Caller pressed emergency code. Skip all gates. Escalate immediately."})
                            log.warning(f"[{session.call_sid[:8]}] EMERGENCY DTMF code entered: {dtmf_input}")

                        session.messages.append({"role": "user", "content": f"[DTMF input: {dtmf_input}]"})
                        session.messages.append({
                            "role": "system",
                            "content": f"The caller entered customer code {dtmf_input} via keypad. Call lookup_client with this code to authenticate them."
                        })
                        asyncio.create_task(process_dtmf_turn(session))

            elif event == "stop":
                log.info(f"[{session.call_sid[:8]}] Stream stopped")
                break

    except WebSocketDisconnect:
        log.info(f"[{session.call_sid[:8]}] WebSocket disconnected")
    except Exception as e:
        log.error(f"[{session.call_sid[:8]}] Error: {e}")
    finally:
        session.active = False
        session.cancelled = True
        sender_task.cancel()
        if greeting_task:
            greeting_task.cancel()
        asyncio.create_task(post_call_actions(session))
        log.info(f"[{session.call_sid[:8]}] Session ended")


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
