"""Razorpay fee payments for auction creation and per-bid charges."""

from __future__ import annotations

import uuid
from decimal import Decimal
from enum import Enum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuctionFeePaymentKind(str, Enum):
    CREATION = "CREATION"
    BID = "BID"


class AuctionFeeAuctionType(str, Enum):
    DOMAIN = "DOMAIN"
    SOFTWARE = "SOFTWARE"
    COMMUNITY = "COMMUNITY"


class AuctionFeePaymentStatus(str, Enum):
    CREATED = "CREATED"
    COMPLETED = "COMPLETED"
    CONSUMED = "CONSUMED"


class AuctionFeePayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "auction_fee_payments"
    __table_args__ = (
        Index("idx_auction_fee_payments_user_kind", "user_id", "payment_kind"),
        Index("idx_auction_fee_payments_order", "razorpay_order_id"),
        UniqueConstraint("razorpay_order_id", name="uq_auction_fee_payments_order"),
    )

    payment_kind: Mapped[AuctionFeePaymentKind] = mapped_column(
        SAEnum(
            AuctionFeePaymentKind,
            name="auction_fee_payment_kind_enum",
            create_constraint=False,
        ),
        nullable=False,
    )
    auction_type: Mapped[AuctionFeeAuctionType] = mapped_column(
        SAEnum(
            AuctionFeeAuctionType,
            name="auction_fee_auction_type_enum",
            create_constraint=False,
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    auction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    bid_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
    fee_amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    razorpay_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[AuctionFeePaymentStatus] = mapped_column(
        SAEnum(
            AuctionFeePaymentStatus,
            name="auction_fee_payment_status_enum",
            create_constraint=False,
        ),
        default=AuctionFeePaymentStatus.CREATED,
        nullable=False,
    )
