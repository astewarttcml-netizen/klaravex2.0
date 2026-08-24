"""
app/models/external_service_health.py
──────────────────────────────────────
Daily health check results for external services Klara AI depends on
(phase8-003). One row per service per check. Used by the Ops tab
to surface degradation early.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from klara.rarv.runtime import Base


class ServiceStatus:
    up = "up"
    degraded = "degraded"
    down = "down"


class ExternalServiceHealth(Base):
    __tablename__ = "external_service_health"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    service_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error: Mapped[Optional[str]] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
