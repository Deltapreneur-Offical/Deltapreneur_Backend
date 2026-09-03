"""Scheduled meeting between a community-auction requester and profile owner."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.community.community_auction import CommunityAuction
    from app.entity.user.app_user import AppUser


class MeetingSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "meeting_schedules"

    auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community_auctions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lister_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    meeting_link: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_calendar_event_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    calendar_event_link: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    topic: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    auction: Mapped["CommunityAuction"] = relationship(
        "CommunityAuction",
        foreign_keys=[auction_id],
        lazy="joined",
    )
    requester: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[requester_id],
        lazy="joined",
    )
    lister: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[lister_id],
        lazy="joined",
    )
