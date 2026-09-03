from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
)


class CommunityAuction(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    SoftDeleteMixin,
    Base,
):
    __tablename__ = "community_auctions"
    __table_args__ = (
        Index("idx_community_auctions_status_end", "status", "end_time"),
    )

    community_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("community.id"),
        nullable=False,
        index=True,
    )

    created_by: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="PAYMENT_PENDING",
        nullable=False,
    )

    duration: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    min_bid_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    current_highest_bid: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    total_bids: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    current_winner_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    original_end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    listing_fee_order_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    listing_fee_payment_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    listing_fee_paid: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    winner_payment_order_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    winner_payment_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    winner_payment_paid: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    auction_title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    auction_skills: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    work_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    expected_rate: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    available_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    additional_info: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    community = relationship(
        "Community",
        backref="community_auctions",
    )

    creator = relationship(
        "AppUser",
        foreign_keys=[created_by],
        backref="created_community_auctions",
    )

    current_winner = relationship(
        "AppUser",
        foreign_keys=[current_winner_id],
        backref="winning_community_auctions",
    )
