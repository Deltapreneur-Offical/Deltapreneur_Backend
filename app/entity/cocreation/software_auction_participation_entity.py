"""Paid participation fee before bidding on a software auction."""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SoftwareAuctionParticipationStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SoftwareAuctionParticipation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "software_auction_participations"
    __table_args__ = (
        UniqueConstraint(
            "software_auction_id",
            "user_id",
            name="uq_software_auction_participations_auction_user",
        ),
        Index("idx_sap_auction_user", "software_auction_id", "user_id"),
    )

    software_auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_auctions.id", ondelete="CASCADE"),
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
    status: Mapped[SoftwareAuctionParticipationStatus] = mapped_column(
        SAEnum(
            SoftwareAuctionParticipationStatus,
            name="software_auction_participation_status_enum",
            create_constraint=False,
        ),
        default=SoftwareAuctionParticipationStatus.CREATED,
        nullable=False,
    )
