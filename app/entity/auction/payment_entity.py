"""
Payment SQLAlchemy 2.0 entity.

Represents an order/intent created with the gateway (Razorpay).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.utils.enums import PaymentStatus

if TYPE_CHECKING:
    from app.entity.auction.auction_entity import Auction
    from app.entity.auction.transaction_entity import Transaction
    from app.entity.user.app_user import AppUser


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A payment order created for the winner of an auction."""

    __tablename__ = "payments"

    __table_args__ = (
        Index("idx_payment_auction_id", "auction_id"),
        Index("idx_payment_user_id", "user_id"),
        Index("idx_payment_status", "payment_status"),
    )

    auction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auctions.id", ondelete="CASCADE"),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    razorpay_order_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
    )

    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    currency: Mapped[str] = mapped_column(
        String(8),
        default="INR",
        nullable=False,
    )

    payment_status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, name="payment_status_enum"),
        default=PaymentStatus.PENDING,
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
    )

    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    auction: Mapped["Auction"] = relationship(
        "Auction",
        back_populates="payments",
        lazy="joined",
    )

    user: Mapped["AppUser"] = relationship(
        "AppUser",
        foreign_keys=[user_id],
        lazy="joined",
    )

    transactions: Mapped[List["Transaction"]] = relationship(
        "Transaction",
        back_populates="payment",
        primaryjoin=(
            "and_(Transaction.payment_id==Payment.id, "
            "Transaction.is_deleted==False)"
        ),
        cascade="save-update, merge",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Payment id={self.id} order={self.razorpay_order_id} "
            f"status={self.payment_status} amount={self.amount}>"
        )


# String primaryjoin on transactions references Transaction; register early.
from app.entity.auction.transaction_entity import (  # noqa: F401
    Transaction as _Transaction,
)
