"""
app/tasks/gdpr_cleanup.py
──────────────────────────
GDPR data retention enforcement.

Runs daily via Celery Beat.
Anonymises leads whose personal data has passed the retention period.
Anonymisation replaces PII fields with null/placeholder values —
the lead row is kept for analytics (score, status, source).

Art. 17 GDPR: right to erasure requests are handled separately
via a dedicated admin endpoint (to be built in phase 2).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, update

from klara.rarv.runtime import celery_app
from klara.rarv.runtime import get_settings
from klara.rarv.runtime import db_context
from klara.rarv.lead import Lead, LeadStatus

logger = structlog.get_logger(__name__)


@celery_app.task(name="app.tasks.gdpr_cleanup.anonymise_expired_leads", bind=True)
def anonymise_expired_leads(self):
    """Synchronous Celery task that wraps the async implementation."""
    # asyncio.run() required: get_event_loop() is deprecated/raises in Python 3.12 worker threads
    asyncio.run(_anonymise())


async def _anonymise():
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.gdpr_anonymize_after_days)

    async with db_context() as db:
        result = await db.execute(
            select(Lead).where(
                Lead.created_at < cutoff,
                Lead.anonymised_at.is_(None),
                Lead.status != LeadStatus.anonymised,
            )
        )
        leads = result.scalars().all()

        count = 0
        for lead in leads:
            lead.name = "[anonymised]"
            lead.email = None
            lead.phone = None
            lead.gdpr_consent_ip = None
            lead.status = LeadStatus.anonymised
            lead.anonymised_at = datetime.now(timezone.utc)
            count += 1

        if count:
            logger.info("gdpr_cleanup.anonymised", count=count, cutoff=cutoff.isoformat())
        else:
            logger.debug("gdpr_cleanup.nothing_to_anonymise")
