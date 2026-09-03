"""
Transaction SQLAlchemy 2.0 entity.

A Transaction is one attempt / callback against a Payment order.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Enum as SAEnum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.utils.enums import TransactionStatus

if TYPE_CHECKING:
    from app.entity.auction.payment_entity import Payment


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A single payment-gateway transaction attempt linked to a Payment."""

    __tablename__ = "transactions"

    __table_args__ = (
        Index("idx_transaction_payment_id", "payment_id"),
        Index("idx_transaction_status", "transaction_status"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="CASCADE"),
        nullable=False,
    )

    transaction_reference: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    gateway_response: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
    )

    transaction_status: Mapped[TransactionStatus] = mapped_column(
        SAEnum(TransactionStatus, name="transaction_status_enum"),
        default=TransactionStatus.INITIATED,
        nullable=False,
    )

    payment: Mapped["Payment"] = relationship(
        "Payment",
        back_populates="transactions",
        lazy="joined",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Transaction id={self.id} payment={self.payment_id} "
            f"status={self.transaction_status}>"
        )
