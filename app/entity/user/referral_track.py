import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class ReferralTrack(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "referral_tracks"

    referrer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    listing_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    visitor_ip: Mapped[str] = mapped_column(
        String(45),
        nullable=False,
        index=True,
    )
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    points_awarded: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    # ── Share-system dedupe fields (added by migration `share001`) ─────────────
    # All three are DEFERRED so pre-migration SQLAlchemy SELECTs never reference
    # columns that do not exist yet — existing flows keep working until the
    # migration is applied. `share_link_id` links the track back to the share
    # link that produced it. `item_key` is the canonical shared-item identity
    # (e.g. `domain:tidebrew.com`, `marketplace:<uuid>`) used for dedupe across
    # multiple links of the same item. `visitor_key` is the resolved receiver
    # identity (user id, signed visitor cookie uuid, or IP fallback).
    share_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("share_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        deferred=True,
    )
    item_key: Mapped[str | None] = mapped_column(
        String(253),
        nullable=True,
        deferred=True,
    )
    visitor_key: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        deferred=True,
    )

    referrer = relationship("AppUser", foreign_keys=[referrer_id], backref="referrals_sent")
    visitor = relationship("AppUser", foreign_keys=[visitor_id], backref="referrals_received")

    __table_args__ = (
        # Atomic one-reward-per-(referrer, item, receiver) guard. The reward is
        # granted only when an INSERT ... ON CONFLICT DO NOTHING actually inserts
        # a row (rowcount / RETURNING id), which the database serializes.
        Index(
            "uq_referral_referrer_item_visitor_user",
            "referrer_id",
            "item_key",
            "visitor_id",
            unique=True,
            postgresql_where=text("visitor_id IS NOT NULL"),
        ),
        Index(
            "uq_referral_referrer_item_visitor_anon",
            "referrer_id",
            "item_key",
            "visitor_key",
            unique=True,
            postgresql_where=text("visitor_id IS NULL"),
        ),
    )
