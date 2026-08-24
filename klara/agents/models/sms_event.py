"""
app/models/sms_event.py
───────────────────────
SMS event audit log for DIDWW webhook callbacks.

Stores both delivery receipts (DLR) and inbound messages (MO)
from DIDWW HTTP OUT SMS trunks. The webhook receiver always returns
200 OK to the sender — rows are INSERT-only for audit.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SmsEvent(Base):
    __tablename__ = "sms_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return (
            f"<SmsEvent id={self.id} type={self.event_type} "
            f"created={self.created_at}>"
        )
