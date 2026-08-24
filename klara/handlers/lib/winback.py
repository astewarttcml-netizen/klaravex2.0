"""
Winback campaign — auto-email cancelled clients at 30, 60, 90 days post-cancel.

Reason-aware copy:
  - too_expensive → "we have a downgrade tier you might like"
  - not_using     → "have you used X feature? want a refresher?"
  - switching     → "would love to know how it's going on the other side"
  - quality       → personal apology + "what should we have done?"
  - other         → generic warm checkin

Idempotent via UNIQUE (cancellation_id, milestone) constraint on
klaravex_winback_sends.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from .db import get_pool
from .email import send_email

log = logging.getLogger("klaravex.winback")

PORTAL_BASE_URL = os.environ.get("PORTAL_BASE_URL", "https://portal.klaravex.com")


def _copy_for(milestone: str, reason: Optional[str], plan_name: Optional[str], name: Optional[str]) -> tuple[str, str]:
    greeting = f"Hi {name}," if name else "Hi there,"
    plan = plan_name or "your plan"
    if milestone == "day_30":
        if reason == "too_expensive":
            return (
                f"Klaravex now offers a smaller tier",
                f"{greeting}\n\n"
                f"It's been a month since you cancelled {plan}. We get it — pricing has to make sense.\n\n"
                f"We've quietly added a lower tier that covers core IT support without the premium "
                f"compliance or vCISO layer. If that sounds more right-sized, hit reply and I'll get you a code.\n\n"
                f"No pressure either way.\n\n"
                f"— Anthony\n"
            )
        if reason == "not_using":
            return (
                f"30-day checkin from Klaravex",
                f"{greeting}\n\n"
                f"You cancelled {plan} a month ago, mentioning you weren't using it enough.\n\n"
                f"Quick honest question: was that because nothing was breaking? "
                f"Or because the AI wasn't actually answering when you tried it?\n\n"
                f"Both are useful for us to know. Reply with one line if you have a sec.\n\n"
                f"— Anthony\n"
            )
        if reason == "switching":
            return (
                f"How's it going with the other provider?",
                f"{greeting}\n\n"
                f"It's been a month since you switched. Genuinely curious — how is it going?\n\n"
                f"If anything didn't translate well, I'd love to know what to fix on our end. "
                f"And if the door's still open down the road, we're here.\n\n"
                f"— Anthony\n"
            )
        if reason == "quality":
            return (
                f"I owe you an honest follow-up",
                f"{greeting}\n\n"
                f"You cancelled {plan} a month ago and the reason you gave us was quality. "
                f"That sat with me.\n\n"
                f"What specifically didn't meet expectations? I read every reply — you'd be "
                f"helping me make this better for the next person.\n\n"
                f"— Anthony\n"
            )
        return (
            f"Checking in — one month later",
            f"{greeting}\n\n"
            f"One month since you cancelled {plan}. Just checking in — anything we could have done differently?\n\n"
            f"Reply with anything. Even one word is useful.\n\n— Anthony\n"
        )

    if milestone == "day_60":
        return (
            f"Klaravex update — two months in",
            f"{greeting}\n\n"
            f"It's been two months. A few things have shifted on our side:\n\n"
            f"  • The AI now resolves 89% of Tier 1/2 issues without escalation\n"
            f"  • We added a friends-and-family pricing tier\n"
            f"  • Onboarding is now under 30 minutes\n\n"
            f"If anything changed on your end and you want to take another look:\n"
            f"  {PORTAL_BASE_URL}/portal/subscription\n\n"
            f"— Anthony\n"
        )

    # day_90
    return (
        f"One last note from Klaravex",
        f"{greeting}\n\n"
        f"This is the last unprompted note you'll get from me. After 90 days I "
        f"figure either you've moved on for good, or there's actually a problem "
        f"with how I'm reaching out.\n\n"
        f"If you ever want to come back, the door is always open. Same email gets you in.\n\n"
        f"— Anthony\n"
    )


async def send_winback_emails() -> dict:
    """Scan for cancellation_attempts where final_outcome='cancelled' and
    enough time has passed for the next milestone. Send + record."""
    pool = await get_pool()
    now = datetime.now(tz=timezone.utc)
    milestones = [
        ("day_30", timedelta(days=30), timedelta(days=31)),  # 30-31 day window
        ("day_60", timedelta(days=60), timedelta(days=61)),
        ("day_90", timedelta(days=90), timedelta(days=91)),
    ]
    sent = []
    async with pool.acquire() as conn:
        for milestone, lower, upper in milestones:
            rows = await conn.fetch(
                """
                SELECT c.id::text, c.email, c.plan_name, c.reason_category, c.resolved_at,
                       cl.name
                  FROM klaravex_cancellation_attempts c
                  LEFT JOIN klaravex_clients cl ON cl.email = c.email
                 WHERE c.final_outcome = 'cancelled'
                   AND c.resolved_at <= $1 AND c.resolved_at >= $2
                   AND NOT EXISTS (
                     SELECT 1 FROM klaravex_winback_sends w
                      WHERE w.cancellation_id = c.id AND w.milestone = $3
                   )
                 LIMIT 50
                """,
                now - lower, now - upper, milestone,
            )
            for r in rows:
                subject, body = _copy_for(milestone, r["reason_category"], r["plan_name"], r["name"])
                try:
                    await send_email(to=r["email"], subject=subject, body=body)
                    await conn.execute(
                        """
                        INSERT INTO klaravex_winback_sends
                          (cancellation_id, email, milestone, reason_category)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT (cancellation_id, milestone) DO NOTHING
                        """,
                        r["id"], r["email"], milestone, r["reason_category"],
                    )
                    sent.append({"email": r["email"], "milestone": milestone, "reason": r["reason_category"]})
                except Exception as exc:
                    log.warning("winback send failed for %s @ %s: %s", r["email"], milestone, exc)
    return {"sent_count": len(sent), "items": sent}
