"""
app/api/chat.py
───────────────
POST /api/v1/chat/message  — main chat endpoint consumed by the WordPress widget.

Flow:
  request → policy_guard → Klara AI (chat pipeline) → response

Rate limiting and GDPR consent are enforced before any data is persisted.
"""
import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from klara.rarv.runtime import AgentContext
from app.agents.registry import registry
from klara.rarv.runtime import get_settings, Settings
from klara.rarv.runtime import get_db

logger = structlog.get_logger(__name__)
router = APIRouter()

# Language-appropriate fallback strings shown when the pipeline fails to
# produce a chat_intake output.  These are last-resort safety nets — the
# real error is always logged at WARNING level above this point.
# The contact address is pulled from settings at call time so multi-brand
# deployments (.de vs .com) show the right email without a code change.
def _fallback_reply(lang: str, settings: Settings) -> str:
    contact = getattr(settings, "support_contact_email", None) or "hello@klaravex.de"
    if lang == "de":
        return (
            f"Entschuldigung, es gab einen technischen Fehler. "
            f"Bitte versuchen Sie es erneut oder kontaktieren Sie uns unter {contact}."
        )
    return f"Sorry, something went wrong. Please try again or reach us at {contact}."


class ChatStartRequest(BaseModel):
    source: str = Field("discovery_call", description="CTA source: discovery_call | contact_us | assessment")
    language: str = Field("en", description="en|de")
    gdpr_consent: bool = Field(True)


class ChatStartResponse(BaseModel):
    session_token: str
    reply: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_token: str | None = Field(None, description="Existing session token. Omit to start new session.")
    gdpr_consent: bool = Field(True, description="GDPR consent. Defaults to True for embedded website widget.")
    channel: str = Field("chat", description="chat | widget")
    language: str = Field("en", description="Page language code detected by the widget (en|de).")
    name: str | None = Field(None, max_length=200, description="Visitor's name, if known.")
    email: str | None = Field(None, max_length=254, description="Visitor's email, if known.")
    source: str = Field("chat", description="CTA source: chat | discovery_call | contact_us | assessment | personal")


class ChatResponse(BaseModel):
    session_token: str
    reply: str
    qualification_status: str | None = None
    approval_required: bool = False
    approval_id: str | None = None


@router.post("/message", response_model=ChatResponse)
async def chat_message(
    req: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    """
    Main chat endpoint.  Called by the WordPress chat widget on every message.

    Security:
      - GDPR consent enforced at request level
      - No API key required (public endpoint)
      - Session tokens are opaque random strings, not JWTs
      - All input validated by Pydantic
    """
    if not req.gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="GDPR consent is required.",
        )

    session_token = req.session_token or secrets.token_urlsafe(32)

    context = AgentContext(
        db=db,
        settings=settings,
        request_id=getattr(request.state, "request_id", None),
    )

    # Policy guard first
    policy = registry.get("policy_guard")
    policy_result = await policy(
        context,
        {
            "message": req.message,
            "gdpr_consent": req.gdpr_consent,
        },
    )
    if not policy_result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=policy_result.error,
        )

    # Route to correct pipeline based on source
    pipeline = "consumer" if req.source == "personal" else "chat"

    loki = registry.get("loki_orchestrator")
    result = await loki(
        context,
        {
            "pipeline": pipeline,
            "payload": {
                "session_token": session_token,
                "message": req.message,
                "channel": req.channel,
                "gdpr_consent": req.gdpr_consent,
                "language": req.language,
                "visitor_name": req.name,    # optional — may be None
                "visitor_email": req.email,  # optional — may be None
                "source": req.source,
            },
        },
    )

    if result.approval_required:
        return ChatResponse(
            session_token=session_token,
            reply=(
                "Your enquiry has been received. A consultant will review it shortly "
                "and get back to you — usually within one business day."
            ),
            approval_required=True,
            approval_id=result.approval_id,
        )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not process your message. Please try again.",
        )

    # Extract reply from pipeline output.
    # Consumer pipeline: atera_ticket_creator.reply > consumer_intake.reply
    # Business pipeline: routing faq_answer > chat_intake reply
    steps = result.output.get("steps", [])
    lang_key = req.language.lower()[:2] if req.language else "en"
    qual_status = None

    if pipeline == "consumer":
        # Consumer pipeline: prefer ticket confirmation from atera_ticket_creator,
        # fall back to the consumer_intake conversational reply.
        ticket_step = next((s for s in steps if s["agent"] == "atera_ticket_creator"), None)
        intake_step = next((s for s in steps if s["agent"] == "consumer_intake"), None)

        if ticket_step and ticket_step.get("output", {}).get("reply"):
            reply = ticket_step["output"]["reply"]
        elif intake_step and intake_step.get("output", {}).get("reply"):
            reply = intake_step["output"]["reply"]
        else:
            reply = _fallback_reply(lang_key, settings)
    else:
        # Business pipeline: routing faq_answer > chat_intake reply.
        # When the routing agent detects a FAQ and runs faq_responder, its answer
        # is more accurate than the general chat_intake reply — prefer it.
        chat_step = next((s for s in steps if s["agent"] == "chat_intake"), None)
        routing_step = next((s for s in steps if s["agent"] == "routing"), None)

        faq_answer = (
            routing_step.get("output", {}).get("faq_answer")
            if routing_step
            else None
        )

        if faq_answer:
            reply = faq_answer
            qual_status = chat_step["output"].get("qualification_status") if chat_step and chat_step.get("output") else None
        elif chat_step and chat_step.get("output"):
            reply = chat_step["output"]["reply"]
            qual_status = chat_step["output"].get("qualification_status")
        else:
            # Pipeline completed but chat_intake produced no output.
            failed_steps = [
                {"agent": s["agent"], "success": s.get("success"), "error": s.get("error")}
                for s in steps
                if not s.get("success")
            ]
            logger.warning(
                "chat.pipeline_no_reply",
                language=req.language,
                pipeline=pipeline,
                steps_run=len(steps),
                chat_step_found=chat_step is not None,
                chat_step_success=chat_step.get("success") if chat_step else None,
                chat_step_error=chat_step.get("error") if chat_step else None,
                failed_steps=failed_steps,
                session_token_provided=bool(req.session_token),
            )
            reply = _fallback_reply(lang_key, settings)

    return ChatResponse(
        session_token=session_token,
        reply=reply,
        qualification_status=qual_status,
    )


@router.post("/start", response_model=ChatStartResponse)
async def chat_start(
    req: ChatStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ChatStartResponse:
    """
    Proactive intake opener — called by the chat widget when the visitor arrives
    via a CTA button ("Book a Discovery Call", "Contact Us", etc.).

    The AI sends the first message rather than waiting for the visitor to type.
    Returns a new session_token and the AI's opening intake message.
    """
    from app.agents.chat_intake import INTAKE_START_TRIGGER, INTAKE_OPENER_PROMPTS, build_system_prompt
    from klara.rarv.conversation import Conversation, Message, MessageRole
    from anthropic import AsyncAnthropic

    if not req.gdpr_consent:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="GDPR consent is required.",
        )

    session_token = secrets.token_urlsafe(32)
    source = req.source if req.source in INTAKE_OPENER_PROMPTS else "discovery_call"
    lang = req.language.lower()[:2] if req.language else "en"

    # Create conversation
    conversation = Conversation(session_token=session_token)
    db.add(conversation)
    await db.flush()

    # Build proactive system prompt — same base as chat_intake but with opener instruction
    opener_instruction = INTAKE_OPENER_PROMPTS[source]
    system_prompt = build_system_prompt(language=lang)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=400,
            system=system_prompt,
            messages=[{"role": "user", "content": f"{INTAKE_START_TRIGGER}:{source}\n\n{opener_instruction}"}],
        )
        reply_text = response.content[0].text
        from klara.rarv.runtime.llm_cost import track_response
        await track_response(db, agent_name="chat_intake_start", model=settings.anthropic_model, response=response)
    except Exception as exc:
        logger.error("chat.start_failed", source=source, error=str(exc))
        reply_text = _fallback_reply(lang, settings)

    # Persist as assistant message (no user message — AI speaks first)
    assistant_msg = Message(
        conversation_id=conversation.id,
        role=MessageRole.assistant,
        content=reply_text,
        agent_name="chat_intake_start",
    )
    db.add(assistant_msg)
    await db.flush()

    logger.info("chat.start_complete", source=source, language=lang, session_token=session_token[:8])

    return ChatStartResponse(session_token=session_token, reply=reply_text)
