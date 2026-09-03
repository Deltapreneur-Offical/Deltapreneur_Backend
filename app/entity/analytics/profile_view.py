import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ProfileView(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):

    __tablename__ = "profile_views"

    __table_args__ = (
        Index("idx_profile_views_profile_id", "profile_id"),
        Index("idx_profile_views_viewed_at", "viewed_at"),
        Index("idx_profile_views_viewer_id", "viewer_id"),
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False
    )

    viewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    viewer_industry: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    viewer_role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )