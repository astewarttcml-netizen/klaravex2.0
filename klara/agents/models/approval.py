"""
app/models/approval.py
──────────────────────
Approval requests for P3/P4/P5 gated actions.

Every action that writes to client environments, sends outbound
messages, creates proposals, or touches billing MUST have a row
here before execution.  The action payload is stored as JSON so
any agent action can be gated without schema changes.
"""
import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    auto_approved = "auto_approved"  # only for P1/P2 actions in dev mode


class RiskLevel(str, enum.Enum):
    p1 = "P1"   # read-only / informational — no approval needed
    p2 = "P2"   # internal writes — no approval needed
    p3 = "P3"   # outbound / publishing — requires human approval
    p4 = "P4"   # legal / billing / sensitive — requires human approval
    p5 = "P5"   # client environment changes — requires human + second approval


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── What needs approval ───────────────────────────────────────────────────
    action_name: Mapped[str] = mapped_column(String(200), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)       # JSON blob
    justification: Mapped[str | None] = mapped_column(Text)

    # ── Who requested it ──────────────────────────────────────────────────────
    requested_by_agent: Mapped[str] = mapped_column(String(100), nullable=False)
    lead_id: Mapped[str | None] = mapped_column(String(36))          # optional context
    conversation_id: Mapped[str | None] = mapped_column(String(36))

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(30), default=ApprovalStatus.pending, nullable=False, index=True
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(255))     # email of approver
    review_note: Mapped[str | None] = mapped_column(Text)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by ApprovalNotifierAgent after an email digest is sent to Anthony.
    # Prevents re-notification on subsequent sweeps.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<ApprovalRequest id={self.id} action={self.action_name} status={self.status}>"
