"""
app/models/audit.py
───────────────────
Immutable audit log.  Rows are INSERT-only — never updated or deleted
(except via GDPR erasure of PII fields, not the event row itself).

Captures every agent action for compliance, debugging, and billing audit trails.
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Event identity ────────────────────────────────────────────────────────
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # e.g. agent.action, approval.requested, lead.qualified, webhook.received

    agent_name: Mapped[str | None] = mapped_column(String(100), index=True)
    action_name: Mapped[str | None] = mapped_column(String(200))

    # ── Context ───────────────────────────────────────────────────────────────
    lead_id: Mapped[str | None] = mapped_column(String(36), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    approval_id: Mapped[str | None] = mapped_column(String(36))

    # ── Payload ───────────────────────────────────────────────────────────────
    details: Mapped[str | None] = mapped_column(Text)   # JSON — sanitised, no raw PII

    # ── Request context ───────────────────────────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))

    # ── Result ────────────────────────────────────────────────────────────────
    success: Mapped[bool] = mapped_column(default=True, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} event={self.event_type} agent={self.agent_name}>"
