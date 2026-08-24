"""
app/models/report.py
─────────────────────
DailyReport ORM model — persists generated daily reports.

Each row represents one generated report (typically one per day,
but manual triggers via POST /api/v1/reports/trigger can create
multiple rows for the same report_date).
"""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReportType(str):
    daily = "daily"
    weekly = "weekly"  # reserved for future use


class DailyReport(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Report metadata ───────────────────────────────────────────────────────
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(30), nullable=False, default="daily")
    triggered_by: Mapped[str] = mapped_column(
        String(100), nullable=False, default="celery_beat"
    )  # "celery_beat" | "api.manual" | agent name

    # ── Content ───────────────────────────────────────────────────────────────
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    stats_json: Mapped[str | None] = mapped_column(Text)  # JSON snapshot of raw numbers

    # ── Delivery ──────────────────────────────────────────────────────────────
    emailed_to: Mapped[str | None] = mapped_column(String(255))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<DailyReport date={self.report_date} triggered_by={self.triggered_by}>"
