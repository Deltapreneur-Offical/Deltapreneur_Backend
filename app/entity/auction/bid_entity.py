"""
Bid SQLAlchemy 2.0 entity.

One row per submitted bid. Soft-deletable for compliance without hard DELETE.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from app.entity.auction.auction_entity import Auction
    from app.entity.user.app_user import AppUser


class Bid(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A single bid placed on an auction."""

    __tablename__ = "bids"

    __table_args__ = (
        Index("idx_bid_auction_created_at", "auction_id", "created_at"),
        Index("idx_bid_auction_amount", "auction_id", "amount"),
        Index("idx_bid_bidder_id", "bidder_id"),
        Index("ix_bids_created_at", "created_at"),
    )

    auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auctions.id", ondelete="CASCADE"),
        nullable=False,
    )

    bidder_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    bidder_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_winning_bid: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    auction: Mapped["Auction"] = relationship(
        "Auction",
        back_populates="bids",
        lazy="joined",
    )

    bidder: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[bidder_id],
        lazy="joined",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Bid id={self.id} auction={self.auction_id} "
            f"bidder={self.bidder_id} amount={self.amount}>"
        )
