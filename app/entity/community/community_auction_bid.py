from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
)


class CommunityAuctionBid(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    __tablename__ = "community_auction_bids"

    auction_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community_auctions.id"),
        nullable=False,
        index=True,
    )

    bidder_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    bidder_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    bid_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    winning_bid: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    auction = relationship(
        "CommunityAuction",
        backref="bids",
    )

    bidder = relationship(
        "AppUser",
        backref="community_auction_bids",
    )
