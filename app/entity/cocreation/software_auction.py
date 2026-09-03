"""Software auction ORM model (one per software listing)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.cocreation_enums import (
    SoftwareAuctionApprovalStatus,
    SoftwareAuctionDuration,
)
from app.utils.enums import AuctionStatus

if TYPE_CHECKING:
    from app.entity.cocreation.software_auction_bid import SoftwareAuctionBid
    from app.entity.cocreation.software_entity import Software
    from app.entity.user.app_user import AppUser


class SoftwareAuction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "software_auctions"
    __table_args__ = (
        UniqueConstraint("software_id", name="uq_software_auctions_software_id"),
        Index("idx_software_auctions_status", "status"),
        Index("idx_software_auctions_approval", "approval_status"),
        Index("idx_software_auctions_end_time", "end_time"),
        Index("idx_software_auctions_status_end", "status", "end_time"),
    )

    software_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("software_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[AuctionStatus] = mapped_column(
        SAEnum(AuctionStatus, name="auction_status_enum", create_constraint=False),
        default=AuctionStatus.DRAFT,
        nullable=False,
    )
    approval_status: Mapped[SoftwareAuctionApprovalStatus] = mapped_column(
        SAEnum(
            SoftwareAuctionApprovalStatus,
            name="software_auction_approval_status_enum",
            create_constraint=False,
        ),
        default=SoftwareAuctionApprovalStatus.PENDING_APPROVAL,
        nullable=False,
    )
    duration: Mapped[SoftwareAuctionDuration] = mapped_column(
        SAEnum(
            SoftwareAuctionDuration,
            name="software_auction_duration_enum",
            create_constraint=False,
        ),
        nullable=False,
    )
    min_bid_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_highest_bid: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_bids: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    auction_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_code_included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    support_included: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    support_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transfer_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    taken_down_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    taken_down_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    take_down_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    take_down_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    current_winner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    start_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    original_end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    winner_payment_order_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    winner_payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    winner_payment_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    software: Mapped["Software"] = relationship(
        "Software",
        foreign_keys=[software_id],
        back_populates="auction",
        lazy="selectin",
    )
    current_winner: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[current_winner_id],
        lazy="selectin",
    )
    taken_down_by: Mapped[Optional["AppUser"]] = relationship(
        "AppUser",
        foreign_keys=[taken_down_by_id],
        lazy="selectin",
    )
    bids: Mapped[List["SoftwareAuctionBid"]] = relationship(
        "SoftwareAuctionBid",
        back_populates="software_auction",
        cascade="all, delete-orphan",
    )
