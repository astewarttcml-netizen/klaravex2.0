"""
0046 — leads: meeting_booked_at, calendly_event_uri, meeting_start_time

Added by CalendlyWebhookAgent (Phase 8).
Stores confirmed booking metadata on the lead row.
"""
from alembic import op
import sqlalchemy as sa

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("meeting_booked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("meeting_start_time", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("calendly_event_uri", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_leads_meeting_booked_at",
        "leads",
        ["meeting_booked_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_leads_meeting_booked_at", table_name="leads")
    op.drop_column("leads", "calendly_event_uri")
    op.drop_column("leads", "meeting_start_time")
    op.drop_column("leads", "meeting_booked_at")
