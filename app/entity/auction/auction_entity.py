"""
Auction SQLAlchemy 2.0 entity.

UUID PK, soft-delete, timezone-aware timestamps, UUID user FKs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.utils.enums import AuctionDuration, AuctionStatus

if TYPE_CHECKING:
    from app.entity.auction.bid_entity import Bid
    from app.entity.auction.domain_entity import Domain
    from app.entity.auction.payment_entity import Payment
    from app.entity.user.app_user import AppUser


class Auction(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    """Represents a single auction on a domain asset."""

    __tablename__ = "auctions"

    __table_args__ = (
        Index("idx_auction_status_end_time", "status", "end_time"),
        Index("idx_auction_domain_id", "domain_id"),
        Index("idx_auction_created_by", "created_by"),
    )

    domain_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("domains.id", ondelete="RESTRICT"),
        nullable=False,
    )

    status: Mapped[AuctionStatus] = mapped_column(
        SAEnum(AuctionStatus, name="auction_status_enum"),
        default=AuctionStatus.DRAFT,
        nullable=False,
        index=True,
    )

    duration: Mapped[AuctionDuration] = mapped_column(
        SAEnum(AuctionDuration, name="auction_duration_enum"),
        nullable=False,
    )

    min_bid_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    current_highest_bid: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )

    total_bids: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    current_winner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    original_end_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    bids: Mapped[List["Bid"]] = relationship(
        "Bid",
        back_populates="auction",
        primaryjoin="and_(Bid.auction_id==Auction.id, Bid.is_deleted==False)",
        cascade="save-update, merge",
        lazy="selectin",
    )

    current_winner: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[current_winner_id],
        lazy="selectin",
    )

    creator: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[created_by],
        lazy="selectin",
    )

    domain: Mapped["Domain"] = relationship(
        "Domain",
        foreign_keys=[domain_id],
        lazy="selectin",
    )

    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="auction",
        primaryjoin=(
            "and_(Payment.auction_id==Auction.id, Payment.is_deleted==False)"
        ),
        cascade="save-update, merge",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Auction id={self.id} domain={self.domain_id} "
            f"status={self.status} end_time={self.end_time}>"
        )


# Register Domain / Payment before mapper resolves string-based relationships.
from app.entity.auction.domain_entity import Domain as _Domain  # noqa: F401, E402
from app.entity.auction.payment_entity import Payment as _Payment  # noqa: F401, E402
from app.entity.auction.bid_entity import Bid as _Bid  # noqa: F401, E402
