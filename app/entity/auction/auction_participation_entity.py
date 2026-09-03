"""Participation fee records for auction bidding access."""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuctionParticipationType(str, Enum):
    DOMAIN = "DOMAIN"
    SOFTWARE = "SOFTWARE"
    COMMUNITY = "COMMUNITY"


class AuctionParticipationStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AuctionParticipation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "auction_participations"
    __table_args__ = (
        UniqueConstraint(
            "auction_type",
            "auction_id",
            "user_id",
            name="uq_auction_participations_type_auction_user",
        ),
        Index("idx_auction_participation_lookup", "auction_type", "auction_id", "user_id"),
    )

    auction_type: Mapped[AuctionParticipationType] = mapped_column(
        SAEnum(
            AuctionParticipationType,
            name="auction_participation_type_enum",
            create_constraint=False,
        ),
        nullable=False,
    )
    auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    fee_amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[AuctionParticipationStatus] = mapped_column(
        SAEnum(
            AuctionParticipationStatus,
            name="auction_participation_status_enum",
            create_constraint=False,
        ),
        default=AuctionParticipationStatus.CREATED,
        nullable=False,
    )
