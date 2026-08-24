"""
app/models/magic_link.py
─────────────────────────
ORM model for portal_magic_links table.

Security design:
- The raw random token is NEVER stored.  Only its SHA-256 hash (token_hash)
  is persisted.  A compromised database gives an attacker useless hashes.
- Links are single-use: used_at is stamped on first verification.
- Links expire after MAGIC_LINK_TTL_MINUTES (default 15).
- Rate limiting (1 request per email per 5 min) is enforced at the Redis layer
  in the service module, not here.

GDPR note:
- client_id references portal_clients.id (personal data by association).
- Rows with used_at set can be purged after 24 h (no retention value).
- Rows with expires_at < now() and used_at IS NULL are dead — also purgeable.
- A scheduled cleanup task should run daily (add to Celery beat if needed).
"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MagicLink(Base):
    __tablename__ = "portal_magic_links"

    id: Mapped[str] = mapped_column(
        Text, primary_key=True, default=lambda: str(uuid4())
    )

    # References portal_clients.id — no FK constraint to keep migrations independent.
    client_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    # SHA-256 hex digest of the raw token.  The raw token is never stored.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)

    # Hard expiry timestamp — enforced at verification time.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Stamped on first successful verification — prevents replay.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Audit trail — when the link was generated.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<MagicLink id={self.id} client={self.client_id} "
            f"expires={self.expires_at} used={self.used_at}>"
        )
