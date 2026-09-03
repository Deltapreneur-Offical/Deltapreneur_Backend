"""Software auction bid ORM model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.entity.cocreation.software_auction import SoftwareAuction
    from app.entity.user.app_user import AppUser


class SoftwareAuctionBid(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "software_auction_bids"
    __table_args__ = (
        Index("idx_software_auction_bids_auction_id", "software_auction_id"),
    )

    software_auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_auctions.id", ondelete="CASCADE"),
        nullable=False,
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    bidder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    bid_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_winning_bid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    software_auction: Mapped["SoftwareAuction"] = relationship(
        "SoftwareAuction",
        back_populates="bids",
    )
    bidder: Mapped[Optional["AppUser"]] = relationship("AppUser", foreign_keys=[bidder_id])
