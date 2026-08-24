"""
app/models/weekly_growth_report.py
──────────────────────────────────
WeeklyGrowthReport — persisted output of the Klara AI Weekly Growth Advisor
(prod-005).

Each row is one generated report for a given ISO week, holding the rendered
Markdown plus a JSON snapshot of the raw signals used to build it. Sections
are not normalised into rows — the report is a single document, written
once per week by the Celery beat job and read by humans through email and
the admin tooling.
"""
from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WeeklyGrowthReport(Base):
    """One generated weekly growth advisor report."""
    __tablename__ = "weekly_growth_reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )

    # ── Report period ──────────────────────────────────────────────────────
    # The Monday (UTC) of the ISO week the report covers — the previous
    # 7 days are inspected, so the period is [week_start - 7d, week_start).
    week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    iso_year: Mapped[int] = mapped_column(Integer, nullable=False)
    iso_week: Mapped[int] = mapped_column(Integer, nullable=False)

    triggered_by: Mapped[str] = mapped_column(
        String(100), nullable=False, server_default="celery_beat"
    )

    # ── Content ────────────────────────────────────────────────────────────
    report_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    # JSONB snapshot of the signals that produced the report — useful for
    # post-hoc analysis and for the admin UI to render charts without
    # re-parsing the Markdown.
    signals: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # ── Delivery ───────────────────────────────────────────────────────────
    emailed_to: Mapped[str | None] = mapped_column(String(255))
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<WeeklyGrowthReport "
            f"week={self.iso_year}-W{self.iso_week:02d} "
            f"emailed_at={self.emailed_at}>"
        )
