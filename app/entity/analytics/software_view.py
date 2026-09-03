"""Per-viewer software listing analytics rows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SoftwareView(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "software_views"
    __table_args__ = (
        Index("idx_software_views_software_id", "software_id"),
        Index("idx_software_views_viewed_at", "viewed_at"),
        Index("idx_software_views_viewer_id", "viewer_id"),
    )

    software_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    viewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    viewer_industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    viewer_role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
